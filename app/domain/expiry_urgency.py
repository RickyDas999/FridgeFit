from datetime import date
from typing import NamedTuple, Sequence

from app.domain.validation import validate_calendar_date, validate_recipe
from app.persistence.models import InventoryBatch, Recipe

EXPIRING_SOON_DAYS = 2
URGENCY_HORIZON_DAYS = 7
EXPIRING_SOON_BONUS = 0.1


class IngredientUseBy(NamedTuple):
    """When one recipe ingredient needs using: the date that drives its expiry urgency."""

    ingredient_id: int
    use_by_date: date | None
    expiring_soon: bool


class RecipeExpiryUrgency(NamedTuple):
    """How urgently a recipe's ingredients need using, as of a given date.

    A higher score means more urgent: 1.0 means an ingredient must be used today. This is not a
    measure of how fresh the food is.
    """

    score: float
    expired_batches: list[InventoryBatch]
    ingredients: list[IngredientUseBy]


def _earliest_use_by(batches: Sequence[InventoryBatch], as_of: date) -> date | None:
    """Return the earliest use-by date among batches with stock that are not yet expired.

    Args:
        batches: Batches of a single ingredient.
        as_of: The date to measure from.

    Returns:
        The earliest use-by date on or after ``as_of``, or None if no batch with stock has one.
    """
    upcoming = [
        batch.use_by_date
        for batch in batches
        if batch.quantity_remaining > 0
        and batch.use_by_date is not None
        and batch.use_by_date >= as_of
    ]
    return min(upcoming) if upcoming else None


def assess_recipe_expiry_urgency(
    recipe: Recipe, batches_by_ingredient: dict[int, list[InventoryBatch]], as_of: date
) -> RecipeExpiryUrgency:
    """Score how urgently a recipe's ingredients need using, based on their use-by dates.

    The base score comes from the recipe's most urgent ingredient: 1.0 if it must be used
    today, falling linearly to 0 at ``URGENCY_HORIZON_DAYS`` out. Each other ingredient due
    within ``EXPIRING_SOON_DAYS`` adds ``EXPIRING_SOON_BONUS``, capped at 1.0. Recipes with no
    dated ingredients score 0.

    Batches already past their use-by date never raise the score: they are returned as
    warnings, since FridgeFit must not make the user's food-safety decision.

    Each ingredient's use-by date is also returned: the earliest unexpired date among its
    batches with stock (the date its urgency comes from), or None when it has none.

    Args:
        recipe: The recipe to assess. Its ``recipe_ingredients`` must be loadable.
        batches_by_ingredient: Mapping of ``ingredient_id`` to that ingredient's batches.
        as_of: The calendar date to assess urgency on.

    Returns:
        The 0-1 expiry urgency score, any expired batches among the recipe's ingredients, and
        each ingredient's use-by date with whether it is expiring soon.

    Raises:
        InvalidInputError: If the recipe is invalid or ``as_of`` is not a calendar date.
    """
    validate_recipe(recipe)
    validate_calendar_date(as_of)

    days_until_use = []
    expired_batches = []
    ingredients = []
    for recipe_ingredient in recipe.recipe_ingredients:
        batches = batches_by_ingredient.get(recipe_ingredient.ingredient_id, [])
        expired_batches.extend(
            batch
            for batch in batches
            if batch.quantity_remaining > 0
            and batch.use_by_date is not None
            and batch.use_by_date < as_of
        )
        use_by = _earliest_use_by(batches, as_of)
        days = None if use_by is None else (use_by - as_of).days
        if days is not None:
            days_until_use.append(days)
        ingredients.append(IngredientUseBy(
            ingredient_id=recipe_ingredient.ingredient_id,
            use_by_date=use_by,
            expiring_soon=days is not None and days <= EXPIRING_SOON_DAYS,
        ))

    if not days_until_use:
        return RecipeExpiryUrgency(
            score=0.0, expired_batches=expired_batches, ingredients=ingredients
        )

    most_urgent, *others = sorted(days_until_use)
    base = max(0.0, (URGENCY_HORIZON_DAYS - most_urgent) / URGENCY_HORIZON_DAYS)
    bonus = EXPIRING_SOON_BONUS * sum(1 for days in others if days <= EXPIRING_SOON_DAYS)

    return RecipeExpiryUrgency(
        score=min(1.0, base + bonus), expired_batches=expired_batches, ingredients=ingredients
    )
