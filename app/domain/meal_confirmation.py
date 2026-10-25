import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from app.domain.recipe_consumption import plan_recipe_consumption
from app.domain.recipe_macros import calculate_recipe_macros
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
    servings: float,
    consumed_at: datetime,
    name: str | None = None,
    allow_shortfall: bool = False,
    idempotency_key: uuid.UUID | None = None,
) -> MealLog:
    """Atomically log a meal made from a recipe and consume inventory via FEFO.

    Only the servings eaten are made: each ingredient's quantity is scaled by
    ``servings / recipe.servings``, and both inventory consumption and the logged macros
    reflect that scaled amount. Leftovers are never created.

    Every ingredient's consumption is planned before anything is mutated, so
    a rejected confirmation writes nothing. On success, a MealLog,
    MealLogIngredient rows, and batch decrements are committed together.

    Args:
        session: Active database session; this function commits it.
        recipe: The recipe that was made.
        servings: How many servings were made and eaten. Any positive number, including
            fractions and more than the recipe's base serving count.
        consumed_at: When the meal was eaten. Also used as ``depleted_at``
            for any batch this consumption empties.
        name: Optional meal name; defaults to the recipe's name.
        allow_shortfall: If True, confirm even when inventory is short,
            consuming only what is available. Macros and logged quantities
            then reflect the amount actually consumed, not the scaled recipe amount.
        idempotency_key: Optional key stored on the MealLog in the same commit, so a retried
            confirmation can be recognized. Checking for an existing key is the caller's job.

    Returns:
        The committed MealLog.

    Raises:
        InvalidInputError: If the recipe is invalid or ``servings`` is not positive.
        InsufficientInventoryError: If any ingredient is short and
            ``allow_shortfall`` is False.
    """
    consumption = plan_recipe_consumption(
        recipe,
        servings,
        {line.ingredient_id: line.ingredient.batches for line in recipe.recipe_ingredients},
    )
    if consumption.shortfalls and not allow_shortfall:
        raise InsufficientInventoryError(consumption.shortfalls)

    macros = calculate_recipe_macros(recipe, quantity_overrides=consumption.fulfilled_quantities)
    meal_log = MealLog(
        name=name or recipe.name,
        recipe_id=recipe.id,
        calories=macros.calories,
        protein=macros.protein,
        carbs=macros.carbs,
        fat=macros.fat,
        consumed_at=consumed_at,
        idempotency_key=idempotency_key,
    )
    session.add(meal_log)

    for line in consumption.lines:
        # MealLogIngredient enforces quantity > 0, so an ingredient with nothing
        # available gets no traceability row rather than a zero-quantity one.
        if line.quantity_fulfilled > 0:
            session.add(MealLogIngredient(
                meal_log=meal_log,
                ingredient_id=line.recipe_ingredient.ingredient_id,
                quantity=line.quantity_fulfilled,
            ))
        for draw in line.draws:
            draw.batch.quantity_remaining -= draw.quantity
            if draw.batch.quantity_remaining == 0:
                draw.batch.depleted_at = consumed_at

    session.commit()
    return meal_log
