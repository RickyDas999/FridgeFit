from datetime import date, datetime, time, timedelta

import pytest

from app.domain.recent_frequency import (
    assess_recent_frequency,
    group_meal_dates_by_recipe,
    recent_window_start,
)
from app.errors import InvalidInputError
from app.persistence.models import MealLog, Recipe

AS_OF = date(2026, 3, 10)


def make_meal(days_ago, recipe_id=1):
    """Build an unsaved MealLog eaten the given number of days before ``AS_OF``.

    Args:
        days_ago: Days before ``AS_OF`` the meal was eaten; negative means after it.
        recipe_id: Recipe the meal came from, or None for a manual meal.

    Returns:
        A new, unpersisted MealLog.
    """
    eaten_at = datetime.combine(AS_OF - timedelta(days=days_ago), time(12))
    return MealLog(recipe_id=recipe_id, consumed_at=eaten_at)


def make_recipe(recipe_id=1):
    """Build an unsaved Recipe with the given id.

    Args:
        recipe_id: Id to give the recipe, used to match meals.

    Returns:
        A new, unpersisted Recipe.
    """
    return Recipe(id=recipe_id, name="Test Recipe", instructions=[], prep_minutes=10, servings=1)


def frequency(*meals, last_eaten=None):
    """Report recipe 1's recent frequency as of ``AS_OF``.

    Args:
        *meals: Recent meals, as the recent-window query would load them.
        last_eaten: Mapping of ``recipe_id`` to last-eaten date, as the full-history
            ``MAX ... GROUP BY`` query would return it.

    Returns:
        The RecentFrequency for recipe 1.
    """
    meal_dates = group_meal_dates_by_recipe(meals, AS_OF)
    return assess_recent_frequency(make_recipe(1), meal_dates, last_eaten or {}, AS_OF)


def test_never_eaten_recipe_reports_zero_and_no_date():
    """A recipe with no meals reports no recent eating and no last-eaten date."""
    result = frequency()

    assert result.times_eaten_recently == 0
    assert result.last_eaten_on is None


def test_window_covers_today_and_the_six_days_before():
    """Meals from today back to six days ago count; seven days ago does not."""
    result = frequency(make_meal(0), make_meal(6), make_meal(7))

    assert result.times_eaten_recently == 2


def test_window_starts_six_days_before_as_of():
    """The recent window is today plus the six days before it."""
    assert recent_window_start(AS_OF) == AS_OF - timedelta(days=6)


def test_last_eaten_date_looks_beyond_the_window():
    """The last-eaten date comes from full history, even when nothing is recent."""
    result = frequency(last_eaten={1: AS_OF - timedelta(days=20)})

    assert result.times_eaten_recently == 0
    assert result.last_eaten_on == AS_OF - timedelta(days=20)


def test_recent_meal_newer_than_last_eaten_input_wins():
    """A recent meal later than the supplied last-eaten date is reported as last eaten."""
    result = frequency(make_meal(2), last_eaten={1: AS_OF - timedelta(days=20)})

    assert result.last_eaten_on == AS_OF - timedelta(days=2)


def test_meals_after_as_of_are_ignored():
    """Dates after the reporting date neither count nor set the last-eaten date."""
    result = frequency(
        make_meal(-1), make_meal(3), last_eaten={1: AS_OF + timedelta(days=1)}
    )

    assert result.times_eaten_recently == 1
    assert result.last_eaten_on == AS_OF - timedelta(days=3)


def test_manual_and_other_recipe_meals_are_ignored():
    """Only meals and last-eaten dates for this recipe count toward its frequency."""
    result = frequency(
        make_meal(1, recipe_id=None), make_meal(1, recipe_id=2), last_eaten={2: AS_OF}
    )

    assert result.times_eaten_recently == 0
    assert result.last_eaten_on is None


def test_multiple_meals_on_one_day_each_count():
    """Eating a recipe twice in one day counts as two times eaten."""
    assert frequency(make_meal(2), make_meal(2)).times_eaten_recently == 2


def test_datetime_as_of_is_rejected():
    """Recent frequency requires a calendar date, not a datetime."""
    with pytest.raises(InvalidInputError):
        group_meal_dates_by_recipe([], datetime(2026, 3, 10))
    with pytest.raises(InvalidInputError):
        assess_recent_frequency(make_recipe(1), {}, {}, datetime(2026, 3, 10))
