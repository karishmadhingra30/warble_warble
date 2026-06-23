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
    """The result for one species in one spring."""

    year: int
    n: int
    arrival_doy: Optional[int]


def yearly_arrival(year: int, days: Sequence[int]) -> YearArrival:
    """Compute one species-year's arrival date.

    Separated from the download so it can be tested against hand-made data
    with a known answer, which is what ``tests/test_arrivals.py`` does.
    """
    return YearArrival(year=year, n=len(days), arrival_doy=percentile_day(days))


@dataclass
class WindowArrival:
    """The five-year summary for one window (e.g. 2008-2012)."""

    arrival_doy: Optional[int]
    years_used: int
    years_available: int


def window_arrival(years: Sequence[YearArrival]) -> WindowArrival:
    """Take the median of a window's yearly arrival dates.

    The median rather than the mean, because one freak year (a storm that
    grounded migrants, or a patch of missing data) should not drag the window.
    """
    usable = [y.arrival_doy for y in years if y.arrival_doy is not None]
    if not usable:
        return WindowArrival(
            arrival_doy=None, years_used=0, years_available=len(years)
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

    Returns None if either window produced no number, because a shift measured
    against a missing value is not a shift.
    """
    if early.arrival_doy is None or late.arrival_doy is None:
        return None
    return late.arrival_doy - early.arrival_doy
