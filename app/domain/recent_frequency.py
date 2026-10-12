from collections import defaultdict
from datetime import date, timedelta
from typing import NamedTuple, Sequence

from app.domain.validation import validate_calendar_date
from app.persistence.models import MealLog, Recipe

RECENT_WINDOW_DAYS = 7


class RecentFrequency(NamedTuple):
    """How often a recipe has been eaten lately. Informational only; never affects ranking."""

    times_eaten_recently: int
    last_eaten_on: date | None


def recent_window_start(as_of: date) -> date:
    """Return the first day of the recent-frequency window ending on ``as_of``.

    Args:
        as_of: The calendar date the window ends on, inclusive.

    Returns:
        The earliest date that still counts as recent.

    Raises:
        InvalidInputError: If ``as_of`` is not a calendar date.
    """
    validate_calendar_date(as_of)
    return as_of - timedelta(days=RECENT_WINDOW_DAYS - 1)


def group_meal_dates_by_recipe(
    meal_logs: Sequence[MealLog], as_of: date
) -> dict[int, list[date]]:
    """Group the dates meals were eaten by the recipe each meal was made from.

    Manual meals with no recipe, and meals eaten after ``as_of``, are ignored.

    Args:
        meal_logs: The user's meal history.
        as_of: The calendar date to look back from.

    Returns:
        Mapping of ``recipe_id`` to the dates meals from that recipe were eaten.

    Raises:
        InvalidInputError: If ``as_of`` is not a calendar date.
    """
    validate_calendar_date(as_of)

    meal_dates = defaultdict(list)
    for meal_log in meal_logs:
        eaten_on = meal_log.consumed_at.date()
        if meal_log.recipe_id is not None and eaten_on <= as_of:
            meal_dates[meal_log.recipe_id].append(eaten_on)
    return meal_dates


def assess_recent_frequency(
    recipe: Recipe,
    meal_dates_by_recipe: dict[int, list[date]],
    last_eaten_by_recipe: dict[int, date],
    as_of: date,
) -> RecentFrequency:
    """Report how many times a recipe was eaten recently and when it was last eaten.

    "Recently" is the ``RECENT_WINDOW_DAYS`` ending on ``as_of``, inclusive. The last-eaten date
    covers the full history up to ``as_of``. Callers need not pass full history: the recent
    meals plus each recipe's last-eaten date (e.g. from a ``MAX ... GROUP BY`` query) suffice.
    Dates after ``as_of`` in either input are ignored.

    Args:
        recipe: The recipe to report on.
        meal_dates_by_recipe: Mapping of ``recipe_id`` to meal dates, as returned by
            ``group_meal_dates_by_recipe``. Must include every meal in the recent window.
        last_eaten_by_recipe: Mapping of ``recipe_id`` to the latest date it was eaten.
        as_of: The calendar date to look back from.

    Returns:
        The count of meals within the window and the most recent meal date (None if never).

    Raises:
        InvalidInputError: If ``as_of`` is not a calendar date.
    """
    window_start = recent_window_start(as_of)
    meal_dates = [d for d in meal_dates_by_recipe.get(recipe.id, []) if d <= as_of]

    known_dates = list(meal_dates)
    last_eaten = last_eaten_by_recipe.get(recipe.id)
    if last_eaten is not None and last_eaten <= as_of:
        known_dates.append(last_eaten)

    return RecentFrequency(
        times_eaten_recently=sum(1 for d in meal_dates if d >= window_start),
        last_eaten_on=max(known_dates, default=None),
    )
