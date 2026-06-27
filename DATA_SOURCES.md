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

**Not yet verified against the live GBIF API.** The machine this was built on
has outbound network access restricted to an allowlist that does not include
`api.gbif.org`, so no real request has been made. Everything above is correct
according to GBIF's own documentation, and the client is built to fail loudly
rather than quietly if something differs.

**Do this on your first real run:**

```bash
python pipeline/build.py --taxon-keys
```

It prints each species with the key GBIF returned. Open
`https://www.gbif.org/species/<key>` for a few of them and confirm the bird is
the one you meant. Then:

```bash
python pipeline/build.py --monthly-report
```

Check that the monthly counts look like a bird's year (migrants near zero in
December, a spike in April) before trusting anything downstream. Record the
date you checked in DECISIONS.md.

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
