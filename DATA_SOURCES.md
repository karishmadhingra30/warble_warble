# Data sources

Where every number on the website comes from, which parameters were checked,
and how they were checked.

---

## GBIF

[GBIF](https://www.gbif.org/), the Global Biodiversity Information Facility,
is an open index of species occurrence records contributed by museums,
surveys, government agencies and citizen-science platforms. It needs no API
key, it has a documented REST API, and its data is licensed for reuse.

### Why GBIF and not eBird directly

| option | why not |
|---|---|
| **eBird API 2.0** | Only returns roughly the last 30 days of observations. This project needs 2008. |
| **eBird Basic Dataset** | The full historical archive, but it requires an access request and the download is multiple gigabytes. |
| **GBIF** | Carries the eBird archive back to the beginning, no key, no request form, small targeted queries. |

GBIF is a re-publication of eBird rather than eBird itself, so it lags the
live platform and carries GBIF's own taxonomic interpretation. For a question
about fifteen-year-old records, neither matters.

---

## Endpoints used

### `GET https://api.gbif.org/v1/species/match`

Turns a scientific name into a GBIF `taxonKey`.

| parameter | value | why |
|---|---|---|
| `name` | e.g. `Cardellina pusilla` | the Latin name to match |
| `kingdom` | `Animalia` | narrows the search and avoids plant homonyms |
| `strict` | `false` | allows a fuzzy match, which is then checked before it is trusted |

The response is accepted only if `matchType` is not `NONE`, `rank` is
`SPECIES`, `classKey` is `212` (Aves), and `confidence` is at least 90. See
`_match_is_trustworthy` in `pipeline/species.py`.

### `GET https://api.gbif.org/v1/occurrence/search`

The sightings themselves.

| parameter | value | why |
|---|---|---|
| `taxonKey` | from the match above | which bird |
| `datasetKey` | `4fa7b334-ce0d-4e88-aaae-2e0c138d049e` | eBird only, so the method is identical in both windows |
| `country` | `US` | |
| `gadmGid` | `USA.5_1` | California. See DECISIONS.md section 1 for why this rather than `stateProvince` |
| `hasCoordinate` | `true` | a record GBIF cannot place on a map cannot be placed in California |
| `occurrenceStatus` | `PRESENT` | eBird also records "I looked and it was not there"; those are not sightings |
| `year` | e.g. `2024`, or `2008,2024` for a range | |
| `month` | `1`-`12` | splits the pull so no query gets near the offset ceiling |
| `limit` | `300` max, `0` for a count-only query | |
| `offset` | `100000` max | |

### Paging limits

- A page holds at most **300** records.
- GBIF rejects an **offset above 100,000**.

Together these cap any single query at 100,000 reachable records. That is why
every pull is split by species, then year, then month, with a further split by
day if a month ever exceeds the cap. `limit=0` returns the count with no
records, which is how the pipeline sizes a query before paging it and how the
monthly counts are collected.

### Rate limiting and identification

GBIF is free and unauthenticated. This client sends about **one request per
second** and identifies itself with a descriptive `User-Agent` naming the
project and its repository, so GBIF can get in touch if a script misbehaves.
Every response is cached in `data/raw/`, so a re-run downloads nothing.

---

## What was verified, and how

**Verified against GBIF's published documentation** (the technical docs at
`techdocs.gbif.org`, the dataset page on `gbif.org`, the citation guidelines,
and the `rgbif` client's reference documentation):

- the two endpoint paths and their parameter names
- the 300-record page cap and the 100,000 offset ceiling
- the eBird dataset key `4fa7b334-ce0d-4e88-aaae-2e0c138d049e`
- `gadmGid=USA.5_1` as California, and that `gadmGid` is recommended over
  `stateProvince` because `stateProvince` is free text from the publisher
- GBIF's citation guidance, including the derived-dataset recommendation for
  work built on search-API pulls

**Verified by running the pipeline** against a local stand-in server that
mimics GBIF's response shapes: paging to the end of a result set, the
`endOfRecords` flag, the cache (a second full run made zero network calls),
the retry and backoff path, the twelve-month counting, the wintering
classification, and the arrival arithmetic end to end.

**Verified against the live GBIF API** on 2026-09-22:

- All ten taxon keys resolve to `ACCEPTED`, rank `SPECIES` nodes whose
  canonical names match the names in `pipeline/species.py`.
- Every filter narrows the result set the way it should. Probing Wilson's
  Warbler in April 2024, one filter at a time:

  | filters | records |
  |---|---:|
  | `taxonKey` alone | 27,582 |
  | `+ datasetKey` (eBird only) | 27,090 |
  | `+ country=US` | 22,742 |
  | `+ gadmGid=USA.5_1` | 11,081 |
  | the full set used by the pipeline | 11,081 |
  | `stateProvince=California` instead of `gadmGid` | 11,223 |

  The last two lines are the check on decision 1. The two California filters
  agree to within 1.3%, and `gadmGid` is the slightly stricter of the two,
  which is what you would expect from a filter computed from coordinates
  rather than read from a text field.

- Paging returns exactly what the count promises. Hermit Warbler, April 2010:
  GBIF reported 157 records, the pager retrieved 157, and none were dropped
  for want of a usable date.
- The same probe shows the confound this project exists to handle. Wilson's
  Warbler in April: **1,621** records in 2010, **11,081** in 2024. Seven times
  the records in fourteen years. Almost none of that is seven times the birds.

**Rate actually used.** The committed default is one request per second. The
run that produced the published numbers used one every 0.5 seconds, about
7,000 requests over roughly an hour, to keep the wall-clock time reasonable.
That is still a modest load for this API, but it is worth stating rather than
leaving the reader to assume the default.

**Repeat these checks whenever you re-run:**

```bash
python pipeline/build.py --taxon-keys      # then spot-check gbif.org/species/<key>
python pipeline/build.py --monthly-report  # migrants near zero in December?
```

---

## Citation

GBIF and eBird both ask to be cited, and both are free to use because people
do it. The website footer carries all three of these.

> GBIF.org. *GBIF Occurrence Search*. https://www.gbif.org/occurrence/search

> Cornell Lab of Ornithology. *EOD - eBird Observation Dataset*. Cornell Lab
> of Ornithology. Occurrence dataset https://doi.org/10.15468/aomfnb accessed
> via GBIF.org.

> eBird. *eBird: An online database of bird distribution and abundance* [web
> application]. eBird, Cornell Lab of Ornithology, Ithaca, New York.
> https://www.ebird.org

**If you build on these numbers**, rather than just reading them, GBIF asks
that you register a
[derived dataset](https://www.gbif.org/citation-guidelines). That mints a DOI
for the exact records you used, which is what makes the work reproducible and
what gets the contributing institutions credited. Data pulled through the
search API has no DOI of its own until you do this.

## Licence

eBird records in GBIF are published as
[CC0](https://creativecommons.org/publicdomain/zero/1.0/) (public domain).
Citation is requested as good practice, not as a licence condition.
