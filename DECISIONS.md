# Decisions

Every judgement call in this project, why it was made, and what evidence it
rests on. If a number on the website surprises you, the reason is probably
here.

---

## 1. Filter California with `gadmGid`, not `stateProvince`

**Decision.** Occurrence queries use `gadmGid=USA.5_1` (GADM's code for the
state of California) rather than `stateProvince=California`.

**Why.** `stateProvince` is free text supplied by whoever published the
record. GBIF stores it as typed. `gadmGid` is assigned by GBIF itself from the
record's coordinates against the GADM boundary file, so it cannot be spelled
"CA", "Calif." or left blank. GBIF's own guidance says searching by
`stateProvince` is tricky for exactly this reason and recommends `gadmGid`.

This is a change from the original brief, which named `stateProvince`. The
brief also said to verify the parameters before relying on them, and this is
what verifying them turned up. Every query still sends `country=US` as well,
and `hasCoordinate=true` is required anyway, so no record is included that
GBIF could not place on a map.

---

## 2. Use only the eBird dataset

**Decision.** Every query carries
`datasetKey=4fa7b334-ce0d-4e88-aaae-2e0c138d049e` (EOD, the eBird Observation
Dataset, published by the Cornell Lab of Ornithology).

**Why.** Mixing datasets would break the comparison between our two windows.
Suppose a museum digitises a drawer of 1970s specimens and publishes it in
2019. Those records land in GBIF with their original collection dates, so they
would arrive in our *early* window from a source that did not exist there
before. Any shift we then measured would be partly an artefact of who uploaded
what, and when. One dataset, one collection method, both windows.

---

## 3. Trim occurrence records before caching them

**Decision.** `data/raw/` holds gzipped pages containing eight fields per
record, not GBIF's full response.

**Why.** A full GBIF occurrence record is about 3 KB of JSON, most of it
licence text, publisher identifiers, verbatim taxonomy and media links. A full
run of this project touches on the order of a million records. Keeping
everything would mean a multi-gigabyte cache on a laptop for data we never
read. The fields kept are listed in `KEPT_FIELDS` in `pipeline/fetch.py`:
record key, event date, year, month, day, latitude, longitude, county.

**Since decision 8**, the default run downloads almost no records at all, so
`data/raw/` is now mostly cached count responses and is a few megabytes. This
trimming still applies to `--mode records`.

The honest caveat: this makes `data/raw/` a trimmed cache, not a true raw
archive. If you want the untouched responses, delete `_slim_page` from the
`postprocess=` argument in `GbifClient._occurrence_page` and re-run.

---

## 4. Wintering birds: decided from the monthly counts

Some birds on the list do not leave California in winter. Townsend's Warbler
and Orange-crowned Warbler are the usual suspects along the coast. A January
sighting of a bird that never left is not a spring arrival, and letting those
records into the spring window drags the 10th percentile into midwinter and
makes the species look like it arrives absurdly early.

**We do not settle this from memory.** The pipeline counts sightings in all
twelve months for every species and computes:

```
winter share = (December + January + February) / (April + May)
```

The numerator is the depth of winter, when a long-distance migrant should be
in the tropics. The denominator is peak spring passage. A clean migrant scores
near zero. A bird that winters here scores high.

**The rule, applied automatically in `pipeline/fetch.py`:**

| winter share | label | what happens |
|---|---|---|
| below 0.05 | `good` | clean migrant, dates read as arrival dates |
| 0.05 to 0.20 | `good` | a scattering of winter records, noted but harmless |
| 0.20 to 0.60 | `flagged` | real wintering population; shown on the page with a warning, and its date is not an arrival date |
| 0.60 and above | `excluded` | winter swamps spring, no arrival signal left |
| any, for a control | `control` | never excluded, see below |

**Controls are exempt on purpose.** A California Towhee is present every month,
so it scores very high and the rule above would throw it out. That would
delete the control group. The whole point of a resident bird is to push it
through the identical method and watch what the method does to a bird that
cannot have changed its arrival date.

**Why flag rather than restrict to non-wintering regions.** The third option in
the brief was to keep a wintering species but limit it to inland regions where
it does not winter. We did not take it. Drawing that boundary would be a second
judgement call layered on the first, it would shrink the sample a lot, and it
would make one species' number incomparable with the rest. Flagging keeps the
species visible and keeps the reader informed, which is the honest trade.

<!-- BEGIN MONTHLY EVIDENCE -->
### Evidence

_Not yet filled in. Run `python pipeline/build.py --monthly-report` and this
section is rewritten in place with the real monthly counts and the label each
species earned. Until then, no species has been classified, because
classifying them from memory is the one thing this section exists to prevent._
<!-- END MONTHLY EVIDENCE -->

---

## 5. Leap years are removed from the day-of-year number

**Decision.** Day of year is normalised so that 29 February does not exist.
Every date from 1 March onwards in a leap year has one subtracted from its raw
day-of-year.

**Why.** Raw day-of-year is not comparable across years. In 2023, day 91 is
1 April. In 2024, day 91 is 31 March. Our early window (2008-2012) contains
one leap year and our late window (2020-2024) contains two, so the raw numbers
carry a systematic offset of roughly half a day between the windows, in the
direction of making the late window look earlier. That is small next to the
effect we are looking for, but it is free to remove and it is exactly the kind
of thing that quietly ruins a result.

Records dated 29 February itself are mapped to day 60, the same as 1 March.
That doubles up one day out of 365, in late February when warbler counts are
low, which is the least-bad option available.

---

## 6. Require 100 sightings per species per year

**Decision.** A species-year with fewer than 100 spring sightings is dropped,
and the page reports how many years each species actually used.

**Why.** A 10th percentile computed on 12 sightings is the second-earliest
sighting, which is barely different from a first-sighting date and carries all
of the same problems. 100 puts the 10th percentile at the 10th record, far
enough into the distribution to be a statistic rather than an anecdote. The
threshold is a constant in `pipeline/arrivals.py`, so it is easy to raise and
re-run.

**A window needs at least 3 of its 5 years** to produce a number at all. Two
years is not a median, it is an average of two points, and with our windows it
would often mean comparing 2011-2012 against 2020-2024.

---

## 7. The metric is a percentile, and it is still not perfect

**Decision.** Arrival is the 10th percentile day of the spring's sightings, not
the first sighting.

**Why.** eBird had far fewer users in 2010 than in 2024. More observers means
someone catches the first bird sooner, even if the birds are doing exactly
what they always did. First-sighting date measures birdwatcher growth at least
as much as bird behaviour. A percentile sits inside the bulk of the
distribution where adding observers mostly adds records everywhere rather than
extending the leading edge.

**It is not immune.** If the new observers are distributed differently through
the season, or bird in different places, a percentile moves too. That residual
is what the control species measures, and it is why the controls get a place
on the page rather than a footnote.

---

## 8. Arrival dates are found by counting, not by downloading every sighting

**Decision.** The pipeline computes each spring's 10th percentile day with a
binary search over count queries. Downloading every record still exists as
`--mode records`, but it is no longer the default and did not produce the
published numbers.

**Why.** The obvious method, and the one this project started with, is to
download every sighting and sort them. It works, and it is what the tests
check against. It is also unusable against the real GBIF API.

GBIF's occurrence search gets dramatically slower as the paging offset grows.
Measured on 2026-09-22 with this project's exact filters, one 300-record page
of Wilson's Warbler:

| offset | time for one page |
|---|---:|
| 0 | 1.8 s |
| 3,000 | 1.5 s |
| 11,400 | over 100 s (gave up) |

The documented ceiling is an offset of 100,000, and that limit is real, but it
is not the one that bites. The practical ceiling is somewhere around 10,000.
Several species-years in this study run past 30,000 sightings, and the two
control birds are over 100,000 each across a window. The first attempt at a
full run was managing **one page every six minutes** and would have taken
weeks.

Splitting by day instead of by month would have kept every query shallow, but
at the cost of roughly 14,000 requests and about five hours, to download 1.8
million records we were only ever going to reduce to one number each.

**The insight.** A percentile does not need the records. It needs to know how
many sightings fell on or before each day. A `limit=0` count query answers
exactly that, and it answers in under a second no matter how large the result
set is, because GBIF never has to assemble any records.

So the pipeline fetches the six monthly totals for a spring, works out which
month contains the 10th percentile, and binary searches within it. About
twelve fast requests per species-year, against a hundred or more slow pages.
The whole study is roughly 1,300 requests instead of 7,000, and the cache is
megabytes instead of gigabytes.

**This is not an approximation, and we did not take that on trust.** The
counting method returns the same day the sorting method returns, by
construction, and it was checked against it:

- On the six Wilson's Warbler springs that had been fully downloaded before
  the paging problem was found, both methods return the identical day **and**
  the identical sighting count, including a spring of 24,843 records.
- `tests/test_arrivals.py` runs both methods over hand-made distributions and
  over 300 randomly generated springs and asserts they agree every time. The
  failure this guards against is an off-by-one that only shows up at certain
  sample sizes.
- Both routes end at the same `yearly_arrival_from_summary`, so the
  minimum-sightings rule cannot be applied differently by one than the other.

**A bonus check that fell out of it.** The counting totals match the record
totals exactly, which means no eBird record in this dataset is missing a day.
Had some been dated only to a month, the two totals would have differed and
`records_to_days` would have been quietly dropping them.

**What we gave up.** `data/raw/` no longer accumulates the sightings
themselves, so there is no local archive to re-analyse a different way without
going back to GBIF. If you want one, run `--mode records`, budget several
hours, and expect it to stall on the larger species. That trade is worth it:
the archive was never the point, and an hour-long run that finishes beats a
week-long run that does not.
