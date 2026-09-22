"""
The conductor. Runs the whole pipeline and writes ``site/data/arrivals.json``.

Run it from the repository root:

    python pipeline/build.py                 # the full run
    python pipeline/build.py --taxon-keys    # step 1 only: print the GBIF keys
    python pipeline/build.py --monthly-report  # step 2 only: the wintering evidence

Why this file exists
--------------------
The other three modules each do one thing and know nothing about the others.
This one knows the order. Keeping the order in a single place means you can
read the whole method top to bottom in about a hundred lines, and it means the
pieces stay testable on their own.

What a cold run costs
---------------------
Roughly one HTTP request per second, a few thousand requests, so plan for one
to two hours the first time. Everything is cached in ``data/raw/``, so the
second run takes seconds and you can change the arithmetic and re-run freely.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# Make `import pipeline.x` work when this file is run directly as
# `python pipeline/build.py` rather than as `python -m pipeline.build`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline import arrivals, fetch, species  # noqa: E402


# ---------------------------------------------------------------------------
# The study design, in one place
# ---------------------------------------------------------------------------

# Two five-year windows, fifteen years apart at their midpoints. Five years
# rather than one because a single spring is weather, and weather is noise.
EARLY_WINDOW = (2008, 2012)
LATE_WINDOW = (2020, 2024)

METHOD_DESCRIPTION = (
    "10th percentile day of year, Jan 1 to Jun 30, eBird records via GBIF"
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = REPO_ROOT / "site" / "data" / "arrivals.json"
DECISIONS_PATH = REPO_ROOT / "DECISIONS.md"


def window_years(window: tuple[int, int]) -> list[int]:
    """Expand ``(2008, 2012)`` into ``[2008, 2009, 2010, 2011, 2012]``."""
    first, last = window
    return list(range(first, last + 1))


# ---------------------------------------------------------------------------
# One species, start to finish
# ---------------------------------------------------------------------------


def build_species(
    sp: species.Species,
    client: fetch.GbifClient,
    verbose: bool = True,
    mode: str = "count",
) -> dict:
    """Download, measure and summarise one bird. Returns one JSON-ready dict.

    The steps, in order:

    1. Count sightings in all twelve months, across both windows, and use
       those counts to decide whether wintering birds spoil this species'
       arrival date (see DECISIONS.md section 4).
    2. For every year in both windows, find the 10th percentile day of the
       spring's sightings.
    3. Take the median of each window's yearly numbers, and subtract.

    ``mode`` picks how step 2 is done:

    ``"count"`` (the default)
        Binary search using count queries. About a dozen fast requests per
        species-year, and it never pages, so GBIF's deep-offset slowdown
        never bites. This is what produced the published numbers.
    ``"records"``
        Download every sighting and sort them. Correct, far slower, and
        unusable on the larger species-years. Kept because it is the
        reference the counting path was checked against, and because having
        two independent routes to the same number is worth the extra code.

    The two agree exactly. See DECISIONS.md section 8.
    """
    if verbose:
        print(f"\n=== {sp.common_name} (taxonKey {sp.taxon_key}) ===", flush=True)

    # -- step 1: the shape of this bird's year ----------------------------
    # Counted across both windows together, because the question "does this
    # species winter in California" is about the bird, not about one year.
    monthly = fetch.monthly_counts(client, sp.taxon_key, EARLY_WINDOW[0], LATE_WINDOW[1])
    reliability, note = fetch.classify_wintering(monthly, sp.is_control)
    if verbose:
        print(f"    winter share {fetch.winter_share(monthly):.2f} -> {reliability}")

    # -- step 2: one arrival date per spring ------------------------------
    yearly: list[arrivals.YearArrival] = []
    for year in window_years(EARLY_WINDOW) + window_years(LATE_WINDOW):
        if mode == "count":
            doy, n = fetch.arrival_by_counting(client, sp.taxon_key, year)
            yearly.append(arrivals.yearly_arrival_from_summary(year, doy, n))
        else:
            records = client.spring_records(sp.taxon_key, year)
            days = arrivals.records_to_days(records)
            # yearly_arrival applies the minimum-sightings rule itself and
            # hands back a skipped result rather than raising, so a thin year
            # needs no special case here.
            yearly.append(arrivals.yearly_arrival(year, days))
        if verbose:
            last = yearly[-1]
            shown = arrivals.format_day_of_year(last.arrival_doy) or "no data"
            print(f"    {year}: {last.n:>6} sightings -> {shown}", flush=True)

    by_year = {y.year: y for y in yearly}
    early = arrivals.window_arrival([by_year[y] for y in window_years(EARLY_WINDOW)])
    late = arrivals.window_arrival([by_year[y] for y in window_years(LATE_WINDOW)])
    shift = arrivals.shift_days(early, late)

    if verbose:
        if shift is None:
            print("    shift: not enough usable years")
        else:
            print(
                f"    {arrivals.format_day_of_year(early.arrival_doy)}"
                f" -> {arrivals.format_day_of_year(late.arrival_doy)}"
                f"  ({shift:+d} days)"
            )

    return {
        "common_name": sp.common_name,
        "scientific_name": sp.scientific_name,
        "taxon_key": sp.taxon_key,
        "is_control": sp.is_control,
        "reliability": reliability,
        "reliability_note": note,
        "early_arrival_doy": early.arrival_doy,
        "late_arrival_doy": late.arrival_doy,
        "shift_days": shift,
        "years_used": {"early": early.years_used, "late": late.years_used},
        "winter_share": round(fetch.winter_share(monthly), 3),
        "monthly_counts": [monthly.get(m, 0) for m in fetch.ALL_MONTHS],
        "yearly": [
            {
                "year": y.year,
                "arrival_doy": y.arrival_doy,
                "n": y.n,
                # Thin years stay in the output rather than vanishing, so the
                # page can show honestly where the data runs out.
                "used": y.used,
            }
            for y in yearly
        ],
    }


# ---------------------------------------------------------------------------
# The whole run
# ---------------------------------------------------------------------------


def build_all(
    client: fetch.GbifClient, verbose: bool = True, mode: str = "count"
) -> dict:
    """Run every species and assemble the complete JSON document."""
    birds = species.resolve_all(species.all_species(), client)
    if verbose:
        print(species.format_taxon_table(birds), flush=True)

    results = [
        build_species(sp, client, verbose=verbose, mode=mode) for sp in birds
    ]

    # Sort by shift, most-earlier first, so the page can render the list in
    # order without doing the sorting itself. Species with no shift go last.
    results.sort(
        key=lambda r: (r["shift_days"] is None, r["shift_days"] or 0)
    )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "method": METHOD_DESCRIPTION,
        "measured_by": mode,
        "windows": {"early": list(EARLY_WINDOW), "late": list(LATE_WINDOW)},
        "min_sightings_per_year": arrivals.MIN_SIGHTINGS_PER_YEAR,
        "min_years_per_window": arrivals.MIN_YEARS_PER_WINDOW,
        "arrival_percentile": arrivals.ARRIVAL_PERCENTILE,
        "source": {
            "name": "GBIF occurrence search, EOD - eBird Observation Dataset",
            "dataset_key": fetch.EBIRD_DATASET_KEY,
            "dataset_url": f"https://www.gbif.org/dataset/{fetch.EBIRD_DATASET_KEY}",
            "api": fetch.GBIF_BASE_URL,
        },
        "species": results,
    }


def write_json(document: dict, path: Path = DEFAULT_OUTPUT) -> None:
    """Write the document where the website will look for it.

    Indented with two spaces rather than minified. The file is a few tens of
    kilobytes either way, and a readable diff in git is worth far more than
    the saved bytes: when a re-run changes a number, you want to see which.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")

    # Show a repo-relative path when we can, because that is what the reader
    # recognises, but never crash over it: --out may point anywhere.
    try:
        shown = path.resolve().relative_to(REPO_ROOT)
    except ValueError:
        shown = path.resolve()
    print(f"\nwrote {shown} ({path.stat().st_size / 1024:.1f} KB)")


# ---------------------------------------------------------------------------
# The monthly report, and filing it in DECISIONS.md
# ---------------------------------------------------------------------------

EVIDENCE_START = "<!-- BEGIN MONTHLY EVIDENCE -->"
EVIDENCE_END = "<!-- END MONTHLY EVIDENCE -->"


def monthly_report(client: fetch.GbifClient) -> str:
    """Build the twelve-month table for every species, as markdown.

    This is the evidence behind the wintering decisions. It is written back
    into DECISIONS.md automatically so that the decisions in that file can
    never drift away from the data they were supposedly based on.
    """
    birds = species.resolve_all(species.all_species(), client)

    lines = [
        "### Evidence",
        "",
        f"Counts are eBird records in California, {EARLY_WINDOW[0]}-{LATE_WINDOW[1]},",
        f"pulled {datetime.now(timezone.utc).date().isoformat()}.",
        "",
        "| species | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov | Dec | winter share | label |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]

    for sp in birds:
        counts = fetch.monthly_counts(
            client, sp.taxon_key, EARLY_WINDOW[0], LATE_WINDOW[1]
        )
        label, _ = fetch.classify_wintering(counts, sp.is_control)
        cells = " | ".join(f"{counts.get(m, 0):,}" for m in fetch.ALL_MONTHS)
        share = fetch.winter_share(counts)
        lines.append(
            f"| {sp.common_name} | {cells} | {share:.2f} | `{label}` |"
        )

    lines += [
        "",
        "Read the table across: a clean migrant has near-zero counts in "
        "December, January and February and a spike in April and May. A bird "
        "that winters here does not.",
    ]
    return "\n".join(lines)


def file_evidence_in_decisions(report: str, path: Path = DECISIONS_PATH) -> None:
    """Replace the evidence block in DECISIONS.md with a fresh report."""
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(
        re.escape(EVIDENCE_START) + r".*?" + re.escape(EVIDENCE_END), re.DOTALL
    )
    replacement = f"{EVIDENCE_START}\n{report}\n{EVIDENCE_END}"
    if not pattern.search(text):
        raise RuntimeError(
            f"Could not find the evidence markers in {path}. "
            "They must be present for the report to be filed."
        )
    path.write_text(pattern.sub(replacement, text), encoding="utf-8")
    print(f"updated the evidence section in {path.name}")


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build site/data/arrivals.json from GBIF eBird records.",
    )
    parser.add_argument(
        "--taxon-keys", action="store_true",
        help="resolve and print the GBIF taxon keys, then stop (build order step 1)",
    )
    parser.add_argument(
        "--monthly-report", action="store_true",
        help="print monthly counts and write them into DECISIONS.md, then stop",
    )
    parser.add_argument(
        "--out", type=Path, default=DEFAULT_OUTPUT,
        help="where to write the JSON (default: site/data/arrivals.json)",
    )
    parser.add_argument(
        "--cache-dir", type=Path, default=REPO_ROOT / "data" / "raw",
        help="where to keep downloaded responses (default: data/raw)",
    )
    parser.add_argument(
        "--rate", type=float, default=1.0,
        help="minimum seconds between requests (default: 1.0, please be kind)",
    )
    parser.add_argument(
        "--base-url", default=fetch.GBIF_BASE_URL,
        help=argparse.SUPPRESS,  # testing hook: point at a local stand-in server
    )
    parser.add_argument(
        "--mode", choices=("count", "records"), default="count",
        help="how to find each arrival day: 'count' binary-searches with count "
             "queries (fast, the default); 'records' downloads every sighting "
             "(the slow reference implementation)",
    )
    parser.add_argument("--quiet", action="store_true", help="less progress output")
    args = parser.parse_args(argv)

    client = fetch.GbifClient(
        cache_dir=args.cache_dir,
        base_url=args.base_url,
        min_seconds_between_requests=args.rate,
    )
    verbose = not args.quiet

    if args.taxon_keys:
        birds = species.resolve_all(species.all_species(), client)
        print(species.format_taxon_table(birds))
        print("\nCheck each key at https://www.gbif.org/species/<key> before trusting it.")
        return 0

    if args.monthly_report:
        report = monthly_report(client)
        print("\n" + report)
        file_evidence_in_decisions(report)
        return 0

    document = build_all(client, verbose=verbose, mode=args.mode)
    write_json(document, args.out)
    print(
        f"requests: {client.stats['network_calls']} network, "
        f"{client.stats['cache_hits']} from cache, "
        f"{client.stats['retries']} retries"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
