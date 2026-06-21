"""
Which birds this project studies, and how we turn a bird's name into a GBIF id.

Why this file exists
--------------------
GBIF does not let you search occurrences by "Wilson's Warbler". It wants a
``taxonKey``: an integer id for a node in GBIF's taxonomy, for example
``9622902``. So before we can download a single sighting we have to translate
every name on our list into a key.

Doing that translation by hand would be fragile. Bird taxonomy gets revised:
Nashville Warbler has been shuffled between the genera *Vermivora*,
*Oreothlypis* and *Leiothlypis* in the last twenty years. If we hard-coded a
key and GBIF later merged or split that node, our download would silently
return the wrong bird. Instead we ask GBIF to do the matching at run time and
then we *check its answer* before we trust it.
"""

from __future__ import annotations

# `dataclass` gives us a small record type with almost no boilerplate. We use it
# for Species so that `sp.common_name` reads better than `sp["common_name"]`.
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# The species list
# ---------------------------------------------------------------------------


@dataclass
class Species:
    """One bird on our study list.

    Attributes
    ----------
    common_name:
        What a birder calls it. This is what the web page shows.
    scientific_name:
        The name we send to GBIF's matching service. Latin names are stable
        enough to match on; common names are not (GBIF holds several different
        "Yellow Warbler"-ish vernacular names).
    is_control:
        True for the non-migratory birds. A resident bird cannot arrive
        earlier, so any "shift" we measure for it is pure measurement error.
        That makes the controls the most important rows in the whole project.
    alt_scientific_names:
        Older or alternative Latin names to fall back on if the primary name
        does not match. Warbler genera were reorganised in 2010-2011, so some
        sources still use the old spelling.
    taxon_key:
        Filled in later by :func:`resolve_taxon_key`. ``None`` until then.
    """

    common_name: str
    scientific_name: str
    is_control: bool = False
    alt_scientific_names: list[str] = field(default_factory=list)
    taxon_key: Optional[int] = None


# The eight warblers named in the project brief. All of them are long-distance
# or medium-distance migrants that breed in or pass through California in
# spring, which is exactly the behaviour whose timing we want to measure.
WARBLERS: list[Species] = [
    Species("Wilson's Warbler", "Cardellina pusilla",
            alt_scientific_names=["Wilsonia pusilla"]),
    Species("Yellow Warbler", "Setophaga petechia",
            alt_scientific_names=["Dendroica petechia"]),
    Species("Black-throated Gray Warbler", "Setophaga nigrescens",
            alt_scientific_names=["Dendroica nigrescens"]),
    Species("Hermit Warbler", "Setophaga occidentalis",
            alt_scientific_names=["Dendroica occidentalis"]),
    Species("MacGillivray's Warbler", "Geothlypis tolmiei",
            alt_scientific_names=["Oporornis tolmiei"]),
    Species("Nashville Warbler", "Leiothlypis ruficapilla",
            alt_scientific_names=["Oreothlypis ruficapilla", "Vermivora ruficapilla"]),
    Species("Townsend's Warbler", "Setophaga townsendi",
            alt_scientific_names=["Dendroica townsendi"]),
    Species("Orange-crowned Warbler", "Leiothlypis celata",
            alt_scientific_names=["Oreothlypis celata", "Vermivora celata"]),
]

def all_species() -> list[Species]:
    """Return every bird we study.

    Kept as a function rather than a module-level list so that each call hands
    back a fresh copy. ``resolve_taxon_key`` writes into these objects, and we
    do not want one run's taxon keys leaking into another run's list.
    """
    import copy

    return [copy.deepcopy(sp) for sp in WARBLERS]


# ---------------------------------------------------------------------------
# Name -> GBIF taxon key
# ---------------------------------------------------------------------------

# GBIF's matcher returns a confidence score out of 100 and a `matchType`.
# We refuse anything weaker than this, because a bad match here would poison
# every number downstream and would be very hard to notice on the finished page.
MIN_MATCH_CONFIDENCE = 90

# GBIF's numeric id for the class Aves (birds). We check it as a cheap guard
# against matching an insect or a plant that happens to share a Latin name.
# Homonyms across kingdoms are real: the matcher is not infallible.
AVES_CLASS_KEY = 212


class TaxonMatchError(RuntimeError):
    """Raised when GBIF cannot give us a match we are willing to trust."""


def _match_is_trustworthy(payload: dict) -> tuple[bool, str]:
    """Judge one ``/species/match`` response. Returns (ok, reason).

    Split out from :func:`resolve_taxon_key` so the rules are readable in one
    place and so the tests can exercise them without any network access.
    """
    if payload.get("matchType") in (None, "NONE"):
        return False, "GBIF found no match for this name"

    if payload.get("rank") != "SPECIES":
        return False, f"matched at rank {payload.get('rank')}, not SPECIES"

    if payload.get("classKey") != AVES_CLASS_KEY:
        return False, f"matched outside birds (classKey={payload.get('classKey')})"

    confidence = payload.get("confidence", 0)
    if confidence < MIN_MATCH_CONFIDENCE:
        return False, f"confidence {confidence} is below {MIN_MATCH_CONFIDENCE}"

    # GBIF returns `usageKey` for the name you asked about and `acceptedUsageKey`
    # when that name is a synonym pointing at a different accepted name. We want
    # the accepted one, because that is the node occurrence records hang off.
    if not (payload.get("acceptedUsageKey") or payload.get("usageKey")):
        return False, "response carried no usable taxon key"

    return True, "ok"


def resolve_taxon_key(sp: Species, client) -> Species:
    """Fill in ``sp.taxon_key`` by asking GBIF to match the scientific name.

    Tries the primary scientific name first, then each entry in
    ``alt_scientific_names``. Raises :class:`TaxonMatchError` if none of them
    produce a match we trust, because carrying on with a wrong key is worse
    than stopping.

    ``client`` is a :class:`pipeline.fetch.GbifClient`. It is passed in rather
    than created here so that tests can hand in a fake and so that the caching
    and rate limiting live in exactly one place.
    """
    problems: list[str] = []

    for name in [sp.scientific_name, *sp.alt_scientific_names]:
        payload = client.match_species(name)
        ok, reason = _match_is_trustworthy(payload)
        if ok:
            sp.taxon_key = payload.get("acceptedUsageKey") or payload["usageKey"]
            # Keep GBIF's own spelling of the name. If taxonomy moved on since
            # we wrote this file, the page should show the current name.
            sp.scientific_name = payload.get("species") or sp.scientific_name
            return sp
        problems.append(f"{name!r}: {reason}")

    raise TaxonMatchError(
        f"Could not resolve a GBIF taxon key for {sp.common_name}. "
        + "; ".join(problems)
    )


def resolve_all(species_list: list[Species], client) -> list[Species]:
    """Resolve taxon keys for a whole list, in place, and return it."""
    for sp in species_list:
        resolve_taxon_key(sp, client)
    return species_list


def format_taxon_table(species_list: list[Species]) -> str:
    """Render the resolved list as a plain-text table for eyeballing.

    Step one of the build order in the project brief is "print the keys and
    check them by hand". This is that print. Paste a key into
    ``https://www.gbif.org/species/<key>`` and confirm it is the bird you meant.
    """
    header = f"{'common name':<30} {'scientific name':<28} {'taxonKey':>9}  control"
    lines = [header, "-" * len(header)]
    for sp in species_list:
        key = sp.taxon_key if sp.taxon_key is not None else "-"
        lines.append(
            f"{sp.common_name:<30} {sp.scientific_name:<28} {key:>9}  "
            f"{'yes' if sp.is_control else ''}"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    # Running `python pipeline/species.py` does the taxon lookup and prints the
    # table, so you can check the keys before spending an hour downloading.
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from pipeline.fetch import GbifClient  # noqa: E402  (import after path fix)

    client = GbifClient()
    print(format_taxon_table(resolve_all(all_species(), client)))
