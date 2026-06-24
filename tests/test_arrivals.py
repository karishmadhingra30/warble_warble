"""
Tests for the arrival arithmetic.

These are the tests worth having. The download either works or it fails
loudly; the maths can be wrong and still produce a chart that looks fine. Each
test below uses hand-made data with an answer you can work out on paper, so a
failure tells you the code is wrong rather than that the data moved.

Run them with ``pytest`` from the repository root.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

# Make `import pipeline...` work when pytest is run from the repository root
# without the package being installed.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.arrivals import (  # noqa: E402
    MIN_SIGHTINGS_PER_YEAR,
    YearArrival,
    day_of_year_to_date,
    format_day_of_year,
    normalized_day_of_year,
    percentile_day,
    records_to_days,
    shift_days,
    window_arrival,
    yearly_arrival,
)


# ---------------------------------------------------------------------------
# 1. The 10th percentile, on data with a known answer
# ---------------------------------------------------------------------------


def test_percentile_on_a_hand_made_hundred():
    """Days 1..100, one sighting each. The 10th percentile must be day 10.

    With exactly 100 evenly spread sightings, 10% of them have happened by the
    10th one, which is day 10. If this returns 9 or 11 the index arithmetic is
    off by one.
    """
    days = list(range(1, 101))
    assert percentile_day(days, 0.10) == 10


def test_percentile_is_the_first_day_reaching_the_share():
    """10 sightings: the answer is the 1st in date order, not the 2nd.

    ceil(0.10 * 10) == 1. After one sighting out of ten, exactly 10% have
    happened, so the first one is the answer.
    """
    days = [80, 84, 85, 90, 91, 95, 96, 100, 104, 110]
    assert percentile_day(days, 0.10) == 80


def test_percentile_rounds_the_rank_upwards():
    """15 sightings: 1.5 rounds up to rank 2, because rank 1 is only 6.7%."""
    days = list(range(60, 75))  # 60..74, fifteen consecutive days
    assert percentile_day(days, 0.10) == 61


def test_percentile_ignores_input_order():
    """The function sorts for you; callers must not have to."""
    shuffled = [110, 80, 96, 84, 104, 90, 100, 85, 95, 91]
    assert percentile_day(shuffled, 0.10) == 80


def test_percentile_is_unmoved_by_extra_late_observers():
    """The point of the metric, as a test.

    Same spring, but twice as many people looking, so every day's sightings
    double. A first-sighting date would very likely move earlier. The
    percentile does not move at all.
    """
    thin = [80, 84, 85, 90, 91, 95, 96, 100, 104, 110]
    crowded = sorted(thin * 2)
    assert percentile_day(crowded, 0.10) == percentile_day(thin, 0.10)


def test_percentile_rejects_empty_input():
    """No sightings means no honest answer, so it raises rather than guesses."""
    with pytest.raises(ValueError):
        percentile_day([])


# ---------------------------------------------------------------------------
# 2. Years under the minimum sighting count are skipped
# ---------------------------------------------------------------------------


def test_year_below_the_minimum_is_skipped_with_a_reason():
    sparse = list(range(1, 50))  # 49 sightings, below the threshold of 100
    result = yearly_arrival(2009, sparse)

    assert result.used is False
    assert result.arrival_doy is None
    assert result.n == 49
    assert "49" in result.skipped_reason


def test_year_exactly_at_the_minimum_is_kept():
    """The threshold is inclusive: 100 sightings is enough."""
    days = list(range(1, MIN_SIGHTINGS_PER_YEAR + 1))
    result = yearly_arrival(2010, days)

    assert result.used is True
    assert result.n == MIN_SIGHTINGS_PER_YEAR
    assert result.arrival_doy == 10


def test_window_median_uses_only_the_kept_years():
    """A skipped year must not drag the window's median.

    Four good years at days 100, 102, 104, 106 and one skipped year. The
    median of the four kept years is 103. If the skipped year leaked in as a
    zero or a None the answer would be very different.
    """
    years = [
        YearArrival(2020, 500, 100, True),
        YearArrival(2021, 500, 102, True),
        YearArrival(2022, 20, None, False, "only 20 sightings, need 100"),
        YearArrival(2023, 500, 104, True),
        YearArrival(2024, 500, 106, True),
    ]
    window = window_arrival(years)

    assert window.years_used == 4
    assert window.years_available == 5
    assert window.arrival_doy == 103  # median of 100,102,104,106 -> 103.0


def test_window_with_too_few_usable_years_reports_nothing():
    """Two years is not a five-year median, so the window returns None."""
    years = [
        YearArrival(2008, 500, 100, True),
        YearArrival(2009, 10, None, False, "too few"),
        YearArrival(2010, 10, None, False, "too few"),
        YearArrival(2011, 10, None, False, "too few"),
        YearArrival(2012, 500, 104, True),
    ]
    window = window_arrival(years)

    assert window.arrival_doy is None
    assert window.years_used == 2


# ---------------------------------------------------------------------------
# 3. The sign of the shift: negative means earlier
# ---------------------------------------------------------------------------


def test_shift_is_negative_when_the_bird_arrives_earlier():
    early = window_arrival([YearArrival(y, 500, 95, True) for y in range(2008, 2013)])
    late = window_arrival([YearArrival(y, 500, 88, True) for y in range(2020, 2025)])

    assert shift_days(early, late) == -7


def test_shift_is_positive_when_the_bird_arrives_later():
    early = window_arrival([YearArrival(y, 500, 88, True) for y in range(2008, 2013)])
    late = window_arrival([YearArrival(y, 500, 95, True) for y in range(2020, 2025)])

    assert shift_days(early, late) == 7


def test_shift_is_zero_when_nothing_changed():
    early = window_arrival([YearArrival(y, 500, 91, True) for y in range(2008, 2013)])
    late = window_arrival([YearArrival(y, 500, 91, True) for y in range(2020, 2025)])

    assert shift_days(early, late) == 0


def test_shift_is_none_when_a_window_is_missing():
    early = window_arrival([YearArrival(2008, 10, None, False, "too few")])
    late = window_arrival([YearArrival(y, 500, 91, True) for y in range(2020, 2025)])

    assert shift_days(early, late) is None


# ---------------------------------------------------------------------------
# 4. Day of year converts to the right calendar date, including leap years
# ---------------------------------------------------------------------------


def test_day_one_is_new_years_day():
    assert format_day_of_year(1) == "January 1"


def test_day_ninety_one_is_the_first_of_april():
    assert format_day_of_year(91) == "April 1"
    assert day_of_year_to_date(91).month == 4
    assert day_of_year_to_date(91).day == 1


def test_day_three_six_five_is_new_years_eve():
    assert format_day_of_year(365) == "December 31"


def test_half_days_round_to_a_real_date():
    """A median of an even number of years can land on x.5."""
    assert format_day_of_year(90.5) == "April 1"  # 90.5 rounds to 91


def test_leap_year_dates_normalise_to_the_same_day_number():
    """1 April must be the same number in a leap year and a normal year.

    This is the correction that stops our two windows (one leap year in the
    early one, two in the late one) carrying a built-in tilt.
    """
    assert normalized_day_of_year(date(2023, 4, 1)) == 91   # raw 91
    assert normalized_day_of_year(date(2024, 4, 1)) == 91   # raw 92, minus one


def test_dates_before_the_leap_day_are_untouched():
    assert normalized_day_of_year(date(2023, 2, 1)) == 32
    assert normalized_day_of_year(date(2024, 2, 1)) == 32


def test_the_leap_day_itself_folds_onto_the_first_of_march():
    """29 February and 1 March share day 60. Documented in DECISIONS.md."""
    assert normalized_day_of_year(date(2024, 2, 29)) == 60
    assert normalized_day_of_year(date(2024, 3, 1)) == 60
    assert normalized_day_of_year(date(2023, 3, 1)) == 60


def test_normalised_day_numbers_round_trip_to_the_right_date():
    """Every day of a leap year and a normal year maps back sensibly.

    For dates from 1 March on in a leap year, the normalised number must
    translate back to the same month and day the sighting actually had.
    """
    for year in (2023, 2024):
        for month, day in [(1, 1), (3, 1), (4, 15), (6, 30), (12, 31)]:
            doy = normalized_day_of_year(date(year, month, day))
            back = day_of_year_to_date(doy)
            assert (back.month, back.day) == (month, day), (year, month, day)


# ---------------------------------------------------------------------------
# 5. Turning GBIF rows into day numbers
# ---------------------------------------------------------------------------


def test_records_outside_the_spring_window_are_dropped():
    records = [
        {"year": 2024, "month": 4, "day": 1},    # in
        {"year": 2024, "month": 6, "day": 30},   # in, last day of the window
        {"year": 2024, "month": 7, "day": 1},    # out, July
        {"year": 2024, "month": 11, "day": 3},   # out, November
    ]
    assert sorted(records_to_days(records)) == [91, 181]


def test_records_without_a_day_are_dropped():
    """A month with no day cannot answer a question about timing."""
    records = [
        {"year": 2024, "month": 4, "day": 1},
        {"year": 2024, "month": 4, "day": None},
    ]
    assert records_to_days(records) == [91]


def test_no_records_gives_no_days():
    assert records_to_days([]) == []
