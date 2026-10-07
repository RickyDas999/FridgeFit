from datetime import datetime

from sqlalchemy.orm import Session

from app.domain.fefo_consumption import plan_fefo_consumption
from app.domain.recipe_macros import calculate_recipe_macros
from app.persistence.models import MealLog, MealLogIngredient, Recipe


class InsufficientInventoryError(Exception):
    def __init__(self, shortfalls: dict[int, tuple[float, float]]):
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
    consumption_plans = {}
    fulfilled_quantities = {}
    shortfalls = {}

    for recipe_ingredient in recipe.recipe_ingredients:
        available_batches = [b for b in recipe_ingredient.ingredient.batches if b.quantity_remaining > 0]
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
