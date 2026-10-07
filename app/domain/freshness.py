from datetime import date
from typing import NamedTuple, Sequence

from app.domain.validation import validate_calendar_date, validate_recipe
from app.persistence.models import InventoryBatch, Recipe

EXPIRING_SOON_DAYS = 2
URGENCY_HORIZON_DAYS = 7
EXPIRING_SOON_BONUS = 0.1


class RecipeFreshness(NamedTuple):
    """Freshness assessment for a recipe's ingredients as of a given date."""

    score: float
    expired_batches: list[InventoryBatch]


def _days_until_use(batches: Sequence[InventoryBatch], as_of: date) -> int | None:
    """Return days until the earliest use-by date among usable, unexpired batches.

    Args:
        batches: Batches of a single ingredient.
        as_of: The date to measure from.

    Returns:
        Days until the earliest use-by date, or None if no batch with stock has an
        unexpired use-by date.
    """
    upcoming = [
        batch.use_by_date
        for batch in batches
        if batch.quantity_remaining > 0
        and batch.use_by_date is not None
        and batch.use_by_date >= as_of
    ]
    return (min(upcoming) - as_of).days if upcoming else None


def assess_recipe_freshness(
    recipe: Recipe, batches_by_ingredient: dict[int, list[InventoryBatch]], as_of: date
) -> RecipeFreshness:
    """Score how much a recipe would help use up ingredients nearing their use-by date.

    The base score comes from the recipe's most urgent ingredient: 1.0 if it must be used
    today, falling linearly to 0 at ``URGENCY_HORIZON_DAYS`` out. Each other ingredient due
    within ``EXPIRING_SOON_DAYS`` adds ``EXPIRING_SOON_BONUS``, capped at 1.0. Recipes with no
    dated ingredients score 0.

    Batches already past their use-by date never raise the score: they are returned as
    warnings, since FridgeFit must not make the user's food-safety decision.

    Args:
        recipe: The recipe to assess. Its ``recipe_ingredients`` must be loadable.
        batches_by_ingredient: Mapping of ``ingredient_id`` to that ingredient's batches.
        as_of: The calendar date to assess freshness on.

    Returns:
        The 0-1 freshness score and any expired batches among the recipe's ingredients.

    Raises:
        InvalidInputError: If the recipe is invalid or ``as_of`` is not a calendar date.
    """
    validate_recipe(recipe)
    validate_calendar_date(as_of)

    days_until_use = []
    expired_batches = []
    for recipe_ingredient in recipe.recipe_ingredients:
        batches = batches_by_ingredient.get(recipe_ingredient.ingredient_id, [])
        expired_batches.extend(
            batch
            for batch in batches
            if batch.quantity_remaining > 0
            and batch.use_by_date is not None
            and batch.use_by_date < as_of
        )
        days = _days_until_use(batches, as_of)
        if days is not None:
            days_until_use.append(days)

    if not days_until_use:
        return RecipeFreshness(score=0.0, expired_batches=expired_batches)

    most_urgent, *others = sorted(days_until_use)
    base = max(0.0, (URGENCY_HORIZON_DAYS - most_urgent) / URGENCY_HORIZON_DAYS)
    bonus = EXPIRING_SOON_BONUS * sum(1 for days in others if days <= EXPIRING_SOON_DAYS)

    return RecipeFreshness(score=min(1.0, base + bonus), expired_batches=expired_batches)
