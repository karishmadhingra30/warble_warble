"""
The arithmetic: turning a pile of sightings into one "arrival date" per year.

Why this file exists
--------------------
This is the part of the project that can be wrong in ways nobody notices. The
download either works or it doesn't. The web page either draws or it doesn't.
But a subtly bad statistic produces a confident-looking chart that means
nothing, so the rules are written out here explicitly rather than handed to a
library function whose default behaviour we would then have to go and read.

The definition, in four steps:

1. Take every sighting of one species in one spring (1 January to 30 June).
2. Turn each sighting's date into a day-of-year number, corrected for leap
   years so that day 91 is 1 April in every year.
3. The **arrival date** is the 10th percentile: the day by which one tenth of
   that spring's sightings had happened.
4. A **window's** arrival date is the median of its five yearly numbers, and
   the **shift** is the late window minus the early window. Negative is
   earlier.

Why the 10th percentile and not the first sighting is the single most
important idea in the project; it is explained at :func:`percentile_day`.
"""

from __future__ import annotations

import calendar   # only for isleap(): the leap-year correction below
import math       # ceil(), for the percentile index
from dataclasses import dataclass
from datetime import date, timedelta
from statistics import median
from typing import Any, Iterable, Optional, Sequence

# pandas does the bulk date handling: parsing thousands of GBIF rows into real
# dates and dropping the unusable ones is a few lines here and a loop with
# three edge cases otherwise.
import pandas as pd


# ---------------------------------------------------------------------------
# The knobs. All of them are argued for in DECISIONS.md.
# ---------------------------------------------------------------------------

# "Arrival" is the day by which this fraction of the spring's sightings had
# happened. 0.10 is a compromise: low enough to be about the front of the
# migration rather than its middle, high enough to sit on real data instead of
# on the one keen birder who went out in February.
ARRIVAL_PERCENTILE = 0.10

# The spring window, as month numbers. 1 January to 30 June.
SPRING_MONTHS = (1, 2, 3, 4, 5, 6)

# A species-year with fewer sightings than this is thrown away rather than
# reported. At 100 sightings the 10th percentile is the 10th record; at 12 it
# is the second record, which is a first-sighting date wearing a disguise.
MIN_SIGHTINGS_PER_YEAR = 100

# A five-year window needs at least this many usable years to report a median.
MIN_YEARS_PER_WINDOW = 3

# If a species' own springs inside one window disagree by more than this many
# days, it has no stable arrival date and the shift between windows cannot be
# read. Three weeks. See DECISIONS.md section 9 for where this number came
# from, including the fact that it was added after seeing the first results.
MAX_STABLE_SPREAD_DAYS = 21

# Any non-leap year works as the calendar we translate day numbers back into.
# 2001 is arbitrary and never shown to the reader.
REFERENCE_YEAR = 2001


# ---------------------------------------------------------------------------
# Day of year, and back again
# ---------------------------------------------------------------------------


def normalized_day_of_year(when: date) -> int:
    """Day of year with 29 February removed, so years are comparable.

    The problem this solves: raw day-of-year does not line up across years.
    1 April is day 91 in 2023 but day 92 in 2024, because 2024 has an extra
    day in February. Our early window holds one leap year and our late window
    holds two, so raw numbers carry a small systematic tilt in exactly the
    direction we are trying to measure.

    The fix: in a leap year, every date from 1 March onwards gets one
    subtracted. The result always runs 1 to 365 and always means the same
    calendar date.

    29 February itself becomes day 60, which is also 1 March. One day out of
    365 is doubled up, in a part of the year where warbler counts are low.
    Alternatives (dropping the date, or using fractions) cost more than they
    are worth here; the call is recorded in DECISIONS.md.
    """
    doy = when.timetuple().tm_yday
    if calendar.isleap(when.year) and doy > 60:
        return doy - 1
    return doy


def _round_half_up(value: float) -> int:
    """Round to the nearest integer, with .5 going up.

    Python's built-in ``round`` uses banker's rounding, so ``round(90.5)`` is
    90 and ``round(91.5)`` is 92. For dates that inconsistency is confusing,
    so we do it the way people expect. Every rounding in the pipeline goes
    through here, so a half-day median and the date printed for it can never
    disagree.
    """
    return math.floor(value + 0.5)


def day_of_year_to_date(doy: float) -> date:
    """Turn a normalised day number back into a calendar date.

    Readers do not think in "day 95". They think in "5 April". Every number
    that reaches the web page goes through here first.

    Accepts a float because a window's arrival date is a median, and the median
    of an even number of years lands on a half day. It is rounded to the
    nearest whole day.
    """
    whole = _round_half_up(doy)
    whole = max(1, min(whole, 365))
    return date(REFERENCE_YEAR, 1, 1) + timedelta(days=whole - 1)


def format_day_of_year(doy: Optional[float]) -> Optional[str]:
    """Render a day number as a plain English date, e.g. ``"April 5"``.

    Returns None for None, so callers can pass a missing value straight
    through without a guard.
    """
    if doy is None:
        return None
    when = day_of_year_to_date(doy)
    # %-d is not portable, so the day is formatted separately to avoid a
    # leading zero ("April 05").
    return f"{when.strftime('%B')} {when.day}"


# ---------------------------------------------------------------------------
# The percentile
# ---------------------------------------------------------------------------


def percentile_day(days: Sequence[int], fraction: float = ARRIVAL_PERCENTILE) -> int:
    """The earliest day by which ``fraction`` of the sightings had happened.

    Why not the first sighting date
    -------------------------------
    This is the whole methodological argument of the project, so it is worth
    stating plainly. eBird had a small fraction of its current userbase in
    2010. Many more people are out looking now. The date of the *first*
    sighting of the spring is essentially a measure of how many people were
    looking in early March, because with enough observers somebody will catch
    the vanguard of the migration on its first day. Compare 2010's first
    sighting against 2024's and you will find "earlier arrival" even if not a
    single bird changed its behaviour.

    A percentile does not have that problem in the same way. The 10th
    percentile sits inside the body of the distribution. Doubling the number of
    observers roughly doubles the sightings across the whole season, which
    leaves a percentile where it was. It is not immune (see the control species
    on the web page), but it is far more stable than the leading edge.

    The exact definition
    --------------------
    The smallest day ``d`` in the data such that at least ``fraction`` of all
    sightings fell on or before ``d``. No interpolation between observed days:
    the answer is always a day that actually appears in the data, which is what
    "the date by which 10% had happened" literally means.

    Worked example: 10 sightings, fraction 0.10. ``ceil(0.10 * 10) = 1``, so
    the answer is the 1st sighting in date order, because after one of ten
    sightings exactly 10% have happened.

    Raises ``ValueError`` on empty input, because there is no honest answer.
    """
    if not 0 < fraction <= 1:
        raise ValueError(f"fraction must be in (0, 1], got {fraction}")
    ordered = sorted(days)
    n = len(ordered)
    if n == 0:
        raise ValueError("cannot take a percentile of zero sightings")

    # ceil gives us the first position at which the cumulative share reaches
    # `fraction`; the -1 converts a 1-based rank into a 0-based index.
    index = math.ceil(fraction * n) - 1
    index = max(0, min(index, n - 1))
    return ordered[index]


def percentile_rank(total: int, fraction: float = ARRIVAL_PERCENTILE) -> int:
    """The 1-based position of the percentile within ``total`` sorted values.

    Split out of :func:`percentile_day` so that the counting method below can
    use exactly the same definition. If these two ever disagree, the website
    is showing two different statistics under one name.
    """
    if not 0 < fraction <= 1:
        raise ValueError(f"fraction must be in (0, 1], got {fraction}")
    if total <= 0:
        raise ValueError("cannot take a percentile of zero sightings")
    return max(1, min(math.ceil(fraction * total), total))


def percentile_day_from_cumulative(
    total: int,
    cumulative_at,
    lo: int = 1,
    hi: int = 181,
    fraction: float = ARRIVAL_PERCENTILE,
) -> int:
    """The same percentile, found by binary search instead of by sorting.

    Why this exists
    ---------------
    :func:`percentile_day` needs every sighting in memory. Downloading every
    sighting turned out to be impossible in practice: GBIF's paging slows to a
    crawl past an offset of roughly ten thousand, and several species-years
    here run to thirty thousand records. See DECISIONS.md section 8.

    But the answer never depended on the individual records. The 10th
    percentile day is defined entirely by *how many* sightings fell on or
    before each day, and GBIF will answer that with a count query in under a
    second no matter how large the result set is.

    So: ``cumulative_at(d)`` returns how many of this spring's sightings fell
    on or before normalised day ``d``, and we binary search for the first day
    where that reaches the percentile's rank. About eight probes covers the
    whole spring, instead of a hundred pages of records.

    This is **not an approximation**. It returns the identical day the sorting
    method returns, and ``tests/test_arrivals.py`` asserts that on hand-made
    data where both can be run.

    Parameters
    ----------
    total:
        How many sightings the spring had in all.
    cumulative_at:
        A callable taking a normalised day number and returning the count of
        sightings on or before it. Passed in rather than built here so this
        function stays pure and testable with no network.
    lo, hi:
        The day range to search. Defaults cover 1 January to 30 June.
    """
    target = percentile_rank(total, fraction)
    while lo < hi:
        mid = (lo + hi) // 2
        if cumulative_at(mid) >= target:
            hi = mid
        else:
            lo = mid + 1
    return lo


def normalized_to_calendar(doy: int, year: int) -> tuple[int, int]:
    """Turn a normalised day number back into a (month, day) in a real year.

    The counting method has to ask GBIF about real calendar dates, but it
    searches in normalised day numbers, so something has to translate between
    them. This is that something, and it is where the leap-year correction has
    to be undone exactly as :func:`normalized_day_of_year` applied it.

    In a leap year every normalised day from 60 onwards sits one calendar day
    later than its number suggests, because 29 February was taken out. Day 60
    maps to 1 March, and asking GBIF for "everything up to 1 March" correctly
    sweeps up the 29 February records, which normalise to day 60 as well.
    """
    raw = doy + 1 if (calendar.isleap(year) and doy >= 60) else doy
    when = date(year, 1, 1) + timedelta(days=raw - 1)
    return when.month, when.day


# ---------------------------------------------------------------------------
# Records -> days
# ---------------------------------------------------------------------------


def records_to_days(records: Iterable[dict[str, Any]]) -> list[int]:
    """Convert trimmed GBIF records into a list of normalised day numbers.

    Drops anything we cannot date to a specific day, and anything outside the
    spring window. Both are quiet on purpose: a record with a month but no day
    is common in GBIF and is simply not usable for a question about timing.

    We build the date from GBIF's interpreted ``year``/``month``/``day``
    integers rather than parsing the ``eventDate`` string, because eventDate
    can legitimately be a range ("2020-04-05/2020-04-06") or carry a time and a
    timezone. The integer fields are GBIF's own interpretation and are already
    cleaned up.
    """
    frame = pd.DataFrame(list(records))
    if frame.empty:
        return []

    for column in ("year", "month", "day"):
        if column not in frame.columns:
            return []

    # errors="coerce" turns anything unparseable into NaT instead of raising,
    # which is what we want for a few bad rows in a large download.
    dates = pd.to_datetime(
        frame[["year", "month", "day"]], errors="coerce"
    ).dropna()

    spring = dates[dates.dt.month.isin(SPRING_MONTHS)]
    return [normalized_day_of_year(ts.date()) for ts in spring]


# ---------------------------------------------------------------------------
# One year, one window
# ---------------------------------------------------------------------------


@dataclass
class YearArrival:
    """The result for one species in one spring.

    ``used`` is False when the year was thrown away for having too few
    sightings. Those years still appear in the output so the web page can show
    an honest picture of where the data is thin.
    """

    year: int
    n: int
    arrival_doy: Optional[int]
    used: bool
    skipped_reason: Optional[str] = None


def yearly_arrival_from_summary(
    year: int,
    arrival_doy: Optional[int],
    n: int,
    min_sightings: int = MIN_SIGHTINGS_PER_YEAR,
) -> YearArrival:
    """Apply the minimum-sightings rule to an already-computed arrival day.

    Both ways of getting an arrival date end here, so the threshold and the
    wording of the skip reason live in exactly one place. If the counting
    method and the record method disagreed about whether a year counts, the
    website would quietly depend on which one you happened to run.
    """
    if n < min_sightings:
        return YearArrival(
            year=year,
            n=n,
            arrival_doy=None,
            used=False,
            skipped_reason=f"only {n} sightings, need {min_sightings}",
        )
    return YearArrival(year=year, n=n, arrival_doy=arrival_doy, used=True)


def yearly_arrival(
    year: int,
    days: Sequence[int],
    min_sightings: int = MIN_SIGHTINGS_PER_YEAR,
) -> YearArrival:
    """Compute one species-year's arrival date from a list of day numbers.

    Separated from the download so it can be tested against hand-made data
    with a known answer, which is what ``tests/test_arrivals.py`` does.
    """
    n = len(days)
    if n < min_sightings:
        return yearly_arrival_from_summary(year, None, n, min_sightings)
    return yearly_arrival_from_summary(
        year, percentile_day(days), n, min_sightings
    )


@dataclass
class WindowArrival:
    """The five-year summary for one window (e.g. 2008-2012)."""

    arrival_doy: Optional[int]
    years_used: int
    years_available: int


def window_arrival(
    years: Sequence[YearArrival],
    min_years: int = MIN_YEARS_PER_WINDOW,
) -> WindowArrival:
    """Take the median of a window's usable yearly arrival dates.

    The median rather than the mean, because one freak year (a storm that
    grounded migrants, or a patch of missing data) should not drag the window.

    Returns ``arrival_doy=None`` if too few years survived the minimum-sightings
    rule. Two years is not a five-year median and reporting it as one would be
    the kind of quiet overclaim this project is trying to avoid.
    """
    usable = [y.arrival_doy for y in years if y.used and y.arrival_doy is not None]
    if len(usable) < min_years:
        return WindowArrival(
            arrival_doy=None, years_used=len(usable), years_available=len(years)
        )
    # median() of an even-length list averages the middle two, which can land
    # on a half day. Rounded here so that the shift printed on the page is
    # exactly the difference between the two dates the page shows.
    return WindowArrival(
        arrival_doy=_round_half_up(median(usable)),
        years_used=len(usable),
        years_available=len(years),
    )


def shift_days(early: WindowArrival, late: WindowArrival) -> Optional[int]:
    """Late window minus early window, in days. Negative means earlier.

    The sign convention matters and is easy to get backwards, so it is stated
    everywhere it appears: **negative is earlier**. A warbler that used to
    arrive on 5 April and now arrives on 29 March shifted -7 days.

    Returns None if either window failed its minimum-years test, because a
    shift measured against a missing number is not a shift.
    """
    if early.arrival_doy is None or late.arrival_doy is None:
        return None
    return late.arrival_doy - early.arrival_doy


def window_spread(years: Sequence[YearArrival]) -> Optional[int]:
    """How many days separate the earliest and latest spring in one window.

    This is the measurement's own noise. A species whose five springs land
    within a week of each other has a real arrival date that a five-year
    median describes well. A species whose springs scatter across six weeks
    does not, and no median of them means very much.
    """
    usable = [y.arrival_doy for y in years if y.used and y.arrival_doy is not None]
    if len(usable) < 2:
        return None
    return max(usable) - min(usable)


def is_stable(
    early: Sequence[YearArrival],
    late: Sequence[YearArrival],
    max_spread: int = MAX_STABLE_SPREAD_DAYS,
) -> tuple[bool, Optional[int]]:
    """Is this species' arrival date steady enough to compare? (ok, spread).

    Takes the worse of the two windows, because one unstable window is enough
    to make the comparison meaningless. Returns the spread alongside the
    verdict so the caller can put the actual number in front of the reader
    rather than just a label.

    Why this check has to exist
    ---------------------------
    You cannot measure a shift smaller than the noise in your own
    measurement. Comparing two five-year medians says nothing if the five
    springs behind each median disagree by more than the gap between them.
    Every other guard in this project is about the data going in; this one is
    about whether the answer coming out means anything.
    """
    spreads = [s for s in (window_spread(early), window_spread(late)) if s is not None]
    if not spreads:
        return True, None
    worst = max(spreads)
    return worst <= max_spread, worst
