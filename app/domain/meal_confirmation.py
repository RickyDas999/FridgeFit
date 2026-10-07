from datetime import datetime

from sqlalchemy.orm import Session

from app.domain.fefo_consumption import plan_fefo_consumption
from app.domain.recipe_macros import calculate_recipe_macros
from app.domain.validation import validate_recipe
from app.persistence.models import MealLog, MealLogIngredient, Recipe


class InsufficientInventoryError(Exception):
    """Raised when inventory cannot cover a recipe and no override was given."""

    def __init__(self, shortfalls: dict[int, tuple[float, float]]):
        """Build the error from per-ingredient shortfall details.

        Args:
            shortfalls: Mapping of ``ingredient_id`` to a
                ``(quantity_needed, quantity_available)`` tuple.
        """
        self.shortfalls = shortfalls
        details = ", ".join(
            f"ingredient {ingredient_id}: needed {needed}, available {available}"
            for ingredient_id, (needed, available) in shortfalls.items()
        )
        super().__init__(f"Insufficient inventory to confirm meal: {details}")


def confirm_meal(
    session: Session,
    recipe: Recipe,
    *,
    consumed_at: datetime,
    name: str | None = None,
    allow_shortfall: bool = False,
) -> MealLog:
    """Atomically log a meal made from a recipe and consume inventory via FEFO.

    Every ingredient's consumption is planned before anything is mutated, so
    a rejected confirmation writes nothing. On success, a MealLog,
    MealLogIngredient rows, and batch decrements are committed together.

    Args:
        session: Active database session; this function commits it.
        recipe: The recipe that was made.
        consumed_at: When the meal was eaten. Also used as ``depleted_at``
            for any batch this consumption empties.
        name: Optional meal name; defaults to the recipe's name.
        allow_shortfall: If True, confirm even when inventory is short,
            consuming only what is available. Macros and logged quantities
            then reflect the amount actually consumed, not the recipe amount.

    Returns:
        The committed MealLog.

    Raises:
        InvalidInputError: If the recipe has no ingredients or a non-positive quantity.
        InsufficientInventoryError: If any ingredient is short and
            ``allow_shortfall`` is False.
    """
    validate_recipe(recipe)

    consumption_plans = {}
    fulfilled_quantities = {}
    shortfalls = {}

    for recipe_ingredient in recipe.recipe_ingredients:
        available_batches = [
            b for b in recipe_ingredient.ingredient.batches if b.quantity_remaining > 0
        ]
        plan = plan_fefo_consumption(available_batches, recipe_ingredient.quantity)
        fulfilled = sum(consumption.quantity for consumption in plan)

        consumption_plans[recipe_ingredient] = plan
        fulfilled_quantities[recipe_ingredient.id] = fulfilled

        if fulfilled < recipe_ingredient.quantity:
            shortfalls[recipe_ingredient.ingredient_id] = (recipe_ingredient.quantity, fulfilled)

    if shortfalls and not allow_shortfall:
        raise InsufficientInventoryError(shortfalls)

    macros = calculate_recipe_macros(recipe, quantity_overrides=fulfilled_quantities)
    meal_log = MealLog(
        name=name or recipe.name,
        recipe_id=recipe.id,
        calories=macros.calories,
        protein=macros.protein,
        carbs=macros.carbs,
        fat=macros.fat,
        consumed_at=consumed_at,
    )
    session.add(meal_log)

    for recipe_ingredient, plan in consumption_plans.items():
        actual_quantity = fulfilled_quantities[recipe_ingredient.id]
        # MealLogIngredient enforces quantity > 0, so an ingredient with nothing
        # available gets no traceability row rather than a zero-quantity one.
        if actual_quantity > 0:
            session.add(MealLogIngredient(
                meal_log=meal_log,
                ingredient_id=recipe_ingredient.ingredient_id,
                quantity=actual_quantity,
            ))
        for consumption in plan:
            consumption.batch.quantity_remaining -= consumption.quantity
            if consumption.batch.quantity_remaining == 0:
                consumption.batch.depleted_at = consumed_at

    session.commit()
    return meal_log
