"""
The data pipeline for the "Are California's warblers arriving earlier?" project.

This package runs on a laptop, never on the web server. It talks to GBIF, does
all the arithmetic, and writes one small JSON file into ``site/data/``. The
published web page reads only that JSON file, so the site stays fast, free to
host, and works even if GBIF is down.

Module map, in the order data flows through them:

    species.py   which birds we study, and how we turn a name into a GBIF id
    fetch.py     the GBIF HTTP client: paging, caching, and rate limiting
    arrivals.py  the arithmetic that turns sightings into an "arrival date"
    build.py     the conductor: calls the other three, writes the JSON
"""

__all__ = ["species", "fetch", "arrivals", "build"]
