import math
from typing import Mapping, NamedTuple, Sequence

from app.domain.fefo_consumption import BatchConsumption, plan_fefo_consumption
from app.domain.validation import validate_recipe, validate_servings
from app.persistence.models import InventoryBatch, Recipe, RecipeIngredient


class IngredientConsumption(NamedTuple):
    """What making a recipe would draw for one of its ingredient lines."""

    recipe_ingredient: RecipeIngredient
    quantity_needed: float
    draws: list[BatchConsumption]
    quantity_fulfilled: float


class RecipeConsumption(NamedTuple):
    """What making some servings of a recipe would draw from inventory, and what is short."""

    lines: list[IngredientConsumption]
    # recipe_ingredient_id -> quantity actually available to draw.
    fulfilled_quantities: dict[int, float]
    # ingredient_id -> (quantity_needed, quantity_available), only for real gaps.
    shortfalls: dict[int, tuple[float, float]]


def plan_recipe_consumption(
    recipe: Recipe,
    servings: float,
    batches_by_ingredient: Mapping[int, Sequence[InventoryBatch]],
) -> RecipeConsumption:
    """Plan what making ``servings`` of a recipe would consume, without changing anything.

    Each ingredient's quantity is scaled by ``servings / recipe.servings`` and drawn from that
    ingredient's batches first-expire, first-out. When stock is short, the plan draws only what
    is available and records the gap.

    Args:
        recipe: The recipe to make.
        servings: How many servings are made; any positive number.
        batches_by_ingredient: Mapping of ``ingredient_id`` to its inventory batches. Any object
            with ``ingredient_id``, ``quantity_remaining``, ``use_by_date``, and ``purchased_at``
            works as a batch; an ingredient with no entry has nothing available.

    Returns:
        The per-line draws, the fulfilled quantity per recipe ingredient, and the shortfalls.

    Raises:
        InvalidInputError: If the recipe is invalid or ``servings`` is not positive.
    """
    validate_recipe(recipe)
    validate_servings(servings)
    scale = servings / recipe.servings

    lines = []
    fulfilled_quantities = {}
    shortfalls = {}
    for recipe_ingredient in recipe.recipe_ingredients:
        needed = recipe_ingredient.quantity * scale
        available_batches = [
            b
            for b in batches_by_ingredient.get(recipe_ingredient.ingredient_id, [])
            if b.quantity_remaining > 0
        ]
        draws = plan_fefo_consumption(available_batches, needed)
        fulfilled = sum(draw.quantity for draw in draws)

        lines.append(IngredientConsumption(recipe_ingredient, needed, draws, fulfilled))
        fulfilled_quantities[recipe_ingredient.id] = fulfilled
        # Scaled quantities can be fractional, and summing per-batch draws can land a rounding
        # error below `needed`; only a real gap counts as a shortfall.
        if fulfilled < needed and not math.isclose(fulfilled, needed):
            shortfalls[recipe_ingredient.ingredient_id] = (needed, fulfilled)

    return RecipeConsumption(lines, fulfilled_quantities, shortfalls)
