# Are California's warblers arriving earlier?

**Live site:** https://karishmadhingra30.github.io/warble_warble/

Fifteen years of birdwatcher records, asked one question: do migrating
warblers reach California earlier in spring than they used to?

---

## The question and the answer

**The question.** Eight species of warbler migrate into California every
spring. If springs are warming, they might be showing up sooner. Do the
records say they are?

**The answer.** _Pending the first data run._ The pipeline has not been run
against the live GBIF API yet, so there is no result to state here, and
writing a plausible-sounding one would defeat the point of the project. Run
`python pipeline/build.py`, read the headline the site generates from the real
numbers, and put it here in two sentences. If the answer turns out to be
"not much changed", write that: a clear null result is still a finding, and
the page is built to say so.

## Screenshot

_Added after the first run._ Once `site/data/arrivals.json` has real numbers
in it, serve the site locally (see below), screenshot the top of the page, and
drop it in as `docs/screenshot.png`.

---

## The one methodological idea worth knowing

**We do not use the first sighting of spring, and you should be suspicious of
anyone who does.**

Far more people use eBird now than in 2010. The date of the first sighting is
really a measure of how many people were outside looking in early March: with
enough observers, somebody catches the leading edge of the migration on the
day it arrives. Compare 2010's first sighting to 2024's and you will find
"earlier arrival" that is mostly more binoculars.

**Instead: the 10th percentile day.** For each bird, in each spring, we take
the day by which one tenth of that year's sightings had happened.

> Picture the spring's sightings as a crowd filing through a door. The first
> person through is a fluke. The moment the first tenth are through is a
> property of the crowd. Double the number of people and the first person
> arrives sooner, but the one-tenth mark stays where it was.

Each five-year window (2008-2012 and 2020-2024) gets the median of its five
yearly dates. The shift is the late window minus the early window. Negative
means earlier.

A percentile is much steadier than a first sighting. It is **not immune**,
which is what the next section is about.

---

## The control birds

This is the part that makes the project worth trusting.

Two non-migratory species go through the identical method: **California
Towhee** and **Oak Titmouse**. Both hold the same few acres all year. Neither
can possibly arrive earlier, because neither arrives at all.

So whatever shift the method reports for them is not birds. It is the
measurement drifting, most likely because the people doing the birdwatching
changed. Whatever the warblers show, the controls' shift has to come off the
top before it means anything.

**What the control showed:** _pending the first data run._ The site computes
this automatically and gives it its own panel: median warbler shift, median
resident shift, and the difference. If the residents move as far as the
warblers do, the honest conclusion is that this method cannot detect a change
in these birds, and the page says that in those words.

---

## Architecture

```
  ┌─────────────────────────────────────────────────────────┐
  │  YOUR LAPTOP                     run by hand, now and    │
  │                                  then, never on a server │
  │   pipeline/species.py   name ──► GBIF taxonKey           │
  │   pipeline/fetch.py     ──────► api.gbif.org             │
  │                         ◄────── sightings (cached in     │
  │   pipeline/arrivals.py           data/raw/, gitignored)  │
  │        │  10th percentile, median, subtract              │
  │   pipeline/build.py                                      │
  └────────┼────────────────────────────────────────────────┘
           │ writes  ~20 KB
           ▼
  ┌─────────────────────────────────┐
  │  site/data/arrivals.json        │  committed to git
  └────────┬────────────────────────┘
           │ git push to main
           ▼
  ┌─────────────────────────────────────────────────────────┐
  │  GITHUB PAGES        .github/workflows/pages.yml         │
  │                      publishes site/ as-is              │
  │                                                          │
  │   index.html  +  styles.css  +  app.js  +  arrivals.json │
  │        │                                                 │
  │        └──► fetch('data/arrivals.json') ──► two charts   │
  └─────────────────────────────────────────────────────────┘
                              ▲
                              │  the browser NEVER calls GBIF
```

All the expensive work happens once, on a laptop, in Python. What ships to the
web is a few tens of kilobytes of finished numbers and three static files. The
page never calls GBIF, which is why the site is fast, free to host, and works
even when GBIF is down. It also means a visitor cannot accidentally generate
thousands of API requests by refreshing.

The pipeline is four modules, each with one job:

| file | job |
|---|---|
| `pipeline/species.py` | the bird list, the control flags, name → GBIF taxon key |
| `pipeline/fetch.py` | the only code that touches the network: paging, caching, rate limiting, retries |
| `pipeline/arrivals.py` | the arithmetic: day-of-year, the 10th percentile, medians, the shift |
| `pipeline/build.py` | the order the other three run in, and writing the JSON |

---

## Running it

You need Python 3.10 or newer.

```bash
git clone https://github.com/karishmadhingra30/warble_warble.git
cd warble_warble
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### The pipeline

Work through it in stages the first time, so you catch a problem before
spending an hour on a download.

```bash
# 1. Check the taxon keys by hand before trusting them.
python pipeline/build.py --taxon-keys

# 2. Pull the monthly counts and see the shape of each bird's year.
#    This also rewrites the evidence table in DECISIONS.md.
python pipeline/build.py --monthly-report

# 3. The full run. Writes site/data/arrivals.json.
python pipeline/build.py
```

**Expect the first full run to take one to two hours.** It makes a few
thousand requests at one per second, which is the polite rate for a free
public API. Every response is cached in `data/raw/`, so the second run takes
seconds, and you can change the arithmetic and re-run as often as you like.
The cache is gitignored; delete it to force a fresh download.

### Previewing the site

```bash
cd site
python -m http.server 8000
```

Then open http://localhost:8000. A plain file open (`file://`) will not work,
because the page fetches its JSON and browsers block that on the file
protocol.

### The tests

```bash
pytest
```

They cover the parts that can be wrong without looking wrong: the percentile
arithmetic, the minimum-sightings rule, the sign of the shift, and the
day-of-year to calendar-date conversion including leap years.

### Publishing

Push to `main` and the workflow in `.github/workflows/pages.yml` publishes
`site/`. It does **not** run the pipeline: data is refreshed by running it
locally and committing the JSON.

**Turning Pages on, once:** repository **Settings** → **Pages** →
**Source: GitHub Actions**. Until that is set the workflow runs and then
fails at the deploy step.

---

## Data and citation

Everything comes from the
[EOD - eBird Observation Dataset](https://www.gbif.org/dataset/4fa7b334-ce0d-4e88-aaae-2e0c138d049e),
published by the Cornell Lab of Ornithology and accessed through the
[GBIF occurrence search API](https://techdocs.gbif.org/en/openapi/v1/occurrence).
Records are public domain (CC0); citation is asked for as good practice.

> GBIF.org. *GBIF Occurrence Search*. https://www.gbif.org/occurrence/search
>
> Cornell Lab of Ornithology. *EOD - eBird Observation Dataset*. Occurrence
> dataset https://doi.org/10.15468/aomfnb accessed via GBIF.org.
>
> eBird. *eBird: An online database of bird distribution and abundance* [web
> application]. eBird, Cornell Lab of Ornithology, Ithaca, New York.
> https://www.ebird.org

If you build on these numbers, GBIF asks you to register a
[derived dataset](https://www.gbif.org/citation-guidelines) so the exact
records get a DOI. Full detail, including every parameter and what was
verified how, is in **[DATA_SOURCES.md](DATA_SOURCES.md)**.

---

## Limits

Said plainly, because they matter more than the headline.

- **There are far more birdwatchers now.** The percentile and the control
  birds both push back on this. Neither is a complete fix. A shift smaller
  than the control's shift is noise.
- **Sightings are not a count of birds.** They are a count of times somebody
  wrote a bird down.
- **California is large.** A statewide number hides the coast behaving
  differently from the Central Valley and the Sierra.
- **Some of these birds spend the winter here.** A January record of a bird
  that never left is not an arrival. Species where this swamps the signal are
  dropped and named on the page; mild cases are flagged. The call is made
  from the monthly counts, not from memory.
- **Two windows is not a trend.** This compares one five-year block against
  another. It cannot say whether a change was steady, sudden, or ongoing.
- **Nothing here explains why.** Earlier arrival is consistent with warming
  springs. This project measures timing and offers no evidence about cause.

---

## Decisions

Every judgement call, with the reasoning and the evidence, is written down in
**[DECISIONS.md](DECISIONS.md)**: the California filter, the single-dataset
rule, the trimmed cache, the wintering-bird thresholds, the leap-year
correction, the minimum sightings, and the limits of the metric itself.
