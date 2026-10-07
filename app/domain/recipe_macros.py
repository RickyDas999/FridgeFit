from typing import NamedTuple

from app.persistence.models import Recipe


class RecipeMacros(NamedTuple):
    calories: float
    protein: float
    carbs: float
    fat: float


def calculate_recipe_macros(recipe: Recipe, quantity_overrides: dict[int, float] | None = None) -> RecipeMacros:
    quantity_overrides = quantity_overrides or {}
    calories = protein = carbs = fat = 0.0

    for recipe_ingredient in recipe.recipe_ingredients:
        ingredient = recipe_ingredient.ingredient
        quantity = quantity_overrides.get(recipe_ingredient.id, recipe_ingredient.quantity)
        scale = quantity / ingredient.nutrition_base_quantity
        calories += scale * ingredient.calories_per_base_unit
        protein += scale * ingredient.protein_per_base_unit
        carbs += scale * ingredient.carbs_per_base_unit
        fat += scale * ingredient.fat_per_base_unit

    return RecipeMacros(calories=calories, protein=protein, carbs=carbs, fat=fat)
