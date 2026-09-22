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
    normalized_to_calendar,
    percentile_day_from_cumulative,
    percentile_rank,
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


# ---------------------------------------------------------------------------
# 6. The counting method must give the identical answer to the sorting method
# ---------------------------------------------------------------------------
#
# The published numbers come from the counting method, because downloading
# every record turned out to be impossible against the live API. These tests
# are what let us treat it as the same statistic rather than a cheaper
# approximation of it. If one of them fails, the website is showing something
# other than what it claims to.


def cumulative_from(days):
    """Build a cumulative-count function from a list of days, for testing.

    Stands in for the one that asks GBIF, so the search logic can be tested
    without a network.
    """
    return lambda d: sum(1 for day in days if day <= d)


def test_counting_matches_sorting_on_a_known_case():
    """Days 1..100: both methods must say day 10."""
    days = list(range(1, 101))
    assert percentile_day_from_cumulative(len(days), cumulative_from(days)) == 10
    assert percentile_day(days) == 10


@pytest.mark.parametrize(
    "days",
    [
        [80, 84, 85, 90, 91, 95, 96, 100, 104, 110],
        list(range(60, 75)),
        [100] * 50,                       # every sighting on one day
        [40] + [120] * 99,                # one very early outlier
        list(range(1, 182)) * 3,          # the whole window, three deep
        [5, 5, 5, 5, 200, 200, 200, 200],
    ],
)
def test_counting_matches_sorting_on_many_shapes(days):
    """Whatever the distribution, the two routes land on the same day."""
    assert percentile_day_from_cumulative(
        len(days), cumulative_from(days)
    ) == percentile_day(days)


def test_counting_matches_sorting_on_random_distributions():
    """A few hundred random springs, checked one against the other.

    Random rather than hand-picked, because the failure mode being guarded
    against is an off-by-one that only shows up at particular sample sizes.
    """
    import random

    rng = random.Random(20260922)
    for _ in range(300):
        n = rng.randint(1, 400)
        days = [rng.randint(1, 181) for _ in range(n)]
        assert percentile_day_from_cumulative(
            n, cumulative_from(days)
        ) == percentile_day(days), days


def test_percentile_rank_is_one_based_and_rounds_up():
    assert percentile_rank(100, 0.10) == 10
    assert percentile_rank(10, 0.10) == 1
    assert percentile_rank(15, 0.10) == 2      # 1.5 rounds up
    assert percentile_rank(1, 0.10) == 1       # never below the first record


def test_percentile_rank_rejects_an_empty_spring():
    with pytest.raises(ValueError):
        percentile_rank(0)


# ---------------------------------------------------------------------------
# 7. Normalised day numbers translate back to real calendar dates
# ---------------------------------------------------------------------------
#
# The counting method searches in normalised day numbers but has to ask GBIF
# about real dates, so this translation sits directly under the result.


def test_normalised_day_maps_back_to_the_same_date_it_came_from():
    """Round-trip every spring day of a leap and a non-leap year."""
    for year in (2023, 2024):
        for doy in range(1, 182):
            month, day = normalized_to_calendar(doy, year)
            assert normalized_day_of_year(date(year, month, day)) == doy


def test_leap_year_dates_shift_by_one_after_february():
    """Day 60 is 1 March in both kinds of year, which is the whole point.

    Asking GBIF for "everything up to 1 March 2024" also sweeps in the
    29 February records, and those normalise to day 60 too, so the cumulative
    count stays correct.
    """
    assert normalized_to_calendar(59, 2024) == (2, 28)
    assert normalized_to_calendar(60, 2024) == (3, 1)
    assert normalized_to_calendar(60, 2023) == (3, 1)
    assert normalized_to_calendar(181, 2024) == (6, 30)
    assert normalized_to_calendar(181, 2023) == (6, 30)


# ---------------------------------------------------------------------------
# 8. The minimum-sightings rule is applied identically by both routes
# ---------------------------------------------------------------------------


def test_both_routes_skip_a_thin_year_the_same_way():
    from pipeline.arrivals import yearly_arrival_from_summary

    thin = list(range(1, 50))          # 49 sightings
    by_records = yearly_arrival(2009, thin)
    by_counting = yearly_arrival_from_summary(2009, 12, len(thin))

    assert by_records.used is by_counting.used is False
    assert by_records.skipped_reason == by_counting.skipped_reason
    assert by_records.arrival_doy is by_counting.arrival_doy is None


# ---------------------------------------------------------------------------
# 9. A species whose own springs scatter is flagged as unstable
# ---------------------------------------------------------------------------
#
# You cannot measure a shift smaller than the noise in your own measurement.
# These tests pin the check that says so.


def steady(years, doys):
    return [YearArrival(y, 500, d, True) for y, d in zip(years, doys)]


def test_spread_is_the_gap_between_the_earliest_and_latest_spring():
    from pipeline.arrivals import window_spread

    assert window_spread(steady(range(2008, 2013), [95, 97, 99, 100, 102])) == 7
    assert window_spread(steady(range(2008, 2013), [49, 52, 64, 84, 88])) == 39


def test_spread_ignores_skipped_years():
    from pipeline.arrivals import window_spread

    years = [
        YearArrival(2008, 500, 100, True),
        YearArrival(2009, 10, None, False, "too few"),
        YearArrival(2010, 500, 104, True),
    ]
    assert window_spread(years) == 4


def test_spread_needs_two_years_to_mean_anything():
    from pipeline.arrivals import window_spread

    assert window_spread(steady([2008], [100])) is None
    assert window_spread([]) is None


def test_a_tight_species_is_stable():
    from pipeline.arrivals import is_stable

    early = steady(range(2008, 2013), [95, 97, 99, 100, 102])
    late = steady(range(2020, 2025), [93, 96, 97, 98, 99])
    ok, spread = is_stable(early, late)
    assert ok is True
    assert spread == 7


def test_a_scattered_species_is_not_stable():
    """The real Black-throated Gray Warbler numbers, which prompted the check."""
    from pipeline.arrivals import is_stable

    early = steady(range(2008, 2013), [49, 52, 64, 84, 88])
    late = steady(range(2020, 2025), [62, 71, 85, 88, 91])
    ok, spread = is_stable(early, late)
    assert ok is False
    assert spread == 39


def test_one_bad_window_is_enough_to_fail():
    """A steady early window does not rescue a scattered late one."""
    from pipeline.arrivals import is_stable

    early = steady(range(2008, 2013), [95, 97, 99, 100, 102])
    late = steady(range(2020, 2025), [60, 70, 80, 90, 100])
    ok, spread = is_stable(early, late)
    assert ok is False
    assert spread == 40


def test_the_threshold_is_inclusive():
    from pipeline.arrivals import MAX_STABLE_SPREAD_DAYS, is_stable

    exactly_at = steady([2008, 2009], [100, 100 + MAX_STABLE_SPREAD_DAYS])
    one_over = steady([2008, 2009], [100, 101 + MAX_STABLE_SPREAD_DAYS])
    assert is_stable(exactly_at, [])[0] is True
    assert is_stable(one_over, [])[0] is False
