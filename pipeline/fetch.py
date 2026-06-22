"""
The GBIF HTTP client: one place for paging, caching, rate limiting and retries.

Why this file exists
--------------------
Every other module in the pipeline wants bird sightings. None of them should
have to think about HTTP status codes, page offsets, or how not to hammer a
free public API. All of that lives here, behind a handful of plain methods.

Three rules this client enforces, and why:

1. **Rate limit.** GBIF is free and unauthenticated. We take about one request
   per second. A polite client stays welcome.
2. **Cache everything.** A full run is thousands of requests. If it dies in the
   middle, or you change the arrival maths and re-run, nothing should be
   downloaded twice. Every response lands in ``data/raw/`` as a gzipped JSON
   file, and a cache hit never touches the network.
3. **Never page past GBIF's ceiling.** GBIF caps a page at 300 records and
   refuses any offset beyond 100,000. See :func:`iter_occurrences`.
"""

from __future__ import annotations

import gzip          # the cache files compress ~10x; bird records are repetitive JSON
import json
import time
import hashlib
from pathlib import Path
from typing import Any, Iterator, Optional
from urllib.parse import urlencode

# `requests` is the HTTP library we use for every GBIF call. We use it rather
# than the standard library's urllib because it handles connection reuse,
# query-string encoding and retries with far less code.
import requests


# ---------------------------------------------------------------------------
# Constants, all verified against GBIF's technical documentation.
# See DATA_SOURCES.md for what was checked and when.
# ---------------------------------------------------------------------------

GBIF_BASE_URL = "https://api.gbif.org/v1"

# Hard ceilings imposed by GBIF's occurrence search, not by us.
MAX_PAGE_SIZE = 300        # `limit` cannot exceed this
MAX_OFFSET = 100_000       # `offset` beyond this returns an error

# The eBird Observation Dataset (EOD), published by the Cornell Lab of
# Ornithology. Restricting to this one dataset matters more than it looks:
# if we let every dataset in, a museum digitising its 1970s skin collection in
# 2019 would drop a pile of old records into our late window and shift the
# numbers for reasons that have nothing to do with migration.
EBIRD_DATASET_KEY = "4fa7b334-ce0d-4e88-aaae-2e0c138d049e"

# GADM is a global database of administrative boundaries. USA.5_1 is the state
# of California. We filter on this rather than on `stateProvince=California`
# because stateProvince is free text typed by the data publisher, while gadmGid
# is assigned by GBIF from the record's coordinates. See DECISIONS.md.
CALIFORNIA_GADM_GID = "USA.5_1"

# GBIF asks API users to identify themselves so they can contact you if a
# script misbehaves. A descriptive User-Agent is the polite minimum.
USER_AGENT = (
    "warbler-arrivals/1.0 "
    "(+https://github.com/karishmadhingra30/warble_warble) python-requests"
)


class GbifError(RuntimeError):
    """Raised when GBIF returns something we cannot use and retries are spent."""


# ---------------------------------------------------------------------------
# The client
# ---------------------------------------------------------------------------


class GbifClient:
    """A small, cached, rate-limited wrapper around the GBIF v1 REST API.

    Create one and reuse it for the whole run. It keeps a single HTTP
    connection open and it keeps track of when it last spoke to GBIF, which is
    how the rate limit is enforced.
    """

    def __init__(
        self,
        cache_dir: Path | str = "data/raw",
        base_url: str = GBIF_BASE_URL,
        min_seconds_between_requests: float = 1.0,
        max_retries: int = 4,
        timeout: float = 60.0,
    ) -> None:
        """Set up the client.

        Parameters
        ----------
        cache_dir:
            Where downloaded responses are stored. Gitignored: it is a cache,
            not source, and a full run fills it with hundreds of megabytes.
        base_url:
            Overridable so the tests can point the client at a local stand-in
            server instead of the real GBIF.
        min_seconds_between_requests:
            The rate limit. One second is the number GBIF's own documentation
            suggests for unauthenticated scripting.
        max_retries:
            How many times to retry a request that failed for a reason that
            might be temporary (a 429, a 5xx, a dropped connection).
        timeout:
            Seconds to wait for a response before giving up on one attempt.
        """
        self.base_url = base_url.rstrip("/")
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.min_interval = min_seconds_between_requests
        self.max_retries = max_retries
        self.timeout = timeout

        # A Session reuses the underlying TCP connection between requests.
        # Over thousands of calls that saves a lot of handshake time.
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})

        self._last_request_at: float = 0.0

        # Counters, printed at the end of a run so you can see what happened.
        self.stats = {"cache_hits": 0, "network_calls": 0, "retries": 0}

    # -- caching ----------------------------------------------------------

    def _cache_path(self, path: str, params: dict[str, Any], label: str) -> Path:
        """Work out which file on disk holds the response for this request.

        The filename has two parts: a human-readable label so you can browse
        ``data/raw/`` and understand it, and a short hash of the full query so
        that two requests differing in any parameter never collide.
        """
        canonical = path + "?" + urlencode(sorted(params.items()))
        digest = hashlib.sha1(canonical.encode("utf-8")).hexdigest()[:10]
        safe_label = "".join(c if c.isalnum() or c in "-_" else "-" for c in label)
        return self.cache_dir / f"{safe_label}.{digest}.json.gz"

    def _read_cache(self, path: Path) -> Optional[dict]:
        """Return the cached response at ``path``, or None if it is unusable.

        A truncated file (the run was interrupted mid-write) must not poison
        every future run, so a corrupt cache entry is treated as a miss.
        """
        if not path.exists():
            return None
        try:
            with gzip.open(path, "rt", encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, EOFError, json.JSONDecodeError):
            path.unlink(missing_ok=True)
            return None

    def _write_cache(self, path: Path, payload: dict) -> None:
        """Write a response to the cache atomically.

        We write to a temporary name and then rename. Rename is atomic on every
        filesystem we care about, so a Ctrl-C can never leave a half-written
        file that looks valid.
        """
        tmp = path.with_suffix(path.suffix + ".tmp")
        with gzip.open(tmp, "wt", encoding="utf-8") as fh:
            json.dump(payload, fh)
        tmp.replace(path)

    # -- the one method that actually touches the network ------------------

    def _sleep_for_rate_limit(self) -> None:
        """Wait, if needed, so that requests stay about one second apart."""
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)

    def get(self, path: str, params: dict[str, Any], label: str) -> dict:
        """GET one GBIF endpoint, via the cache, with retries. Returns JSON.

        This is the single choke point for network access in the whole project.
        Everything else calls it. That is deliberate: it means the rate limit
        and the cache cannot be accidentally bypassed by a new code path.
        """
        cache_path = self._cache_path(path, params, label)
        cached = self._read_cache(cache_path)
        if cached is not None:
            self.stats["cache_hits"] += 1
            return cached

        url = f"{self.base_url}/{path.lstrip('/')}"
        last_error: Optional[str] = None

        for attempt in range(self.max_retries + 1):
            if attempt:
                # Exponential backoff: 2s, 4s, 8s, 16s. Backing off rather than
                # retrying immediately is what makes a retry helpful instead of
                # just adding load to a server that is already struggling.
                self.stats["retries"] += 1
                time.sleep(2 ** attempt)

            self._sleep_for_rate_limit()
            try:
                response = self.session.get(url, params=params, timeout=self.timeout)
                self._last_request_at = time.monotonic()
                self.stats["network_calls"] += 1
            except requests.RequestException as exc:
                last_error = f"connection failed: {exc}"
                continue

            # 429 means we are going too fast; 5xx means GBIF is having a
            # moment. Both are worth retrying. A 4xx other than 429 means we
            # built a bad request, and retrying it would never help.
            if response.status_code == 429 or response.status_code >= 500:
                last_error = f"HTTP {response.status_code}"
                continue
            if not response.ok:
                raise GbifError(
                    f"GBIF rejected {url} with HTTP {response.status_code}: "
                    f"{response.text[:300]}"
                )

            try:
                payload = response.json()
            except ValueError as exc:
                last_error = f"response was not JSON: {exc}"
                continue

            self._write_cache(cache_path, payload)
            return payload

        raise GbifError(f"GET {url} failed after {self.max_retries} retries: {last_error}")

    # -- endpoint wrappers -------------------------------------------------

    def match_species(self, scientific_name: str) -> dict:
        """Ask GBIF's fuzzy matcher to turn a Latin name into a taxon record.

        Endpoint: ``/species/match``. Used by :mod:`pipeline.species`.
        """
        return self.get(
            "species/match",
            {"name": scientific_name, "kingdom": "Animalia", "strict": "false"},
            label=f"match-{scientific_name.replace(' ', '_')}",
        )

    def base_occurrence_params(self, taxon_key: int) -> dict[str, Any]:
        """The filters every occurrence query in this project shares.

        Pulled into one method so that the study's definition of "a usable
        California eBird sighting" is written down exactly once.
        """
        return {
            "taxonKey": taxon_key,
            "datasetKey": EBIRD_DATASET_KEY,
            "country": "US",
            "gadmGid": CALIFORNIA_GADM_GID,
            # Without coordinates GBIF cannot place a record in California, and
            # a record we cannot place is a record we cannot use.
            "hasCoordinate": "true",
            # eBird lets observers record "I looked and this species was not
            # there". Those are ABSENT records. They are not sightings.
            "occurrenceStatus": "PRESENT",
        }

    def count(self, params: dict[str, Any], label: str) -> int:
        """Return just the number of records matching ``params``.

        Asking for ``limit=0`` makes GBIF return the count and no records at
        all. That is a very cheap request, so we use it to size a query before
        deciding how to page through it.
        """
        payload = self.get(
            "occurrence/search", {**params, "limit": 0, "offset": 0}, label=label
        )
        return int(payload.get("count", 0))
