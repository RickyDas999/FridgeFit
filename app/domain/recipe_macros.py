from typing import NamedTuple

from app.persistence.models import Recipe


class RecipeMacros(NamedTuple):
    """Total calories, protein, carbs, and fat for a recipe or meal."""

    calories: float
    protein: float
    carbs: float
    fat: float


def calculate_recipe_macros(
    recipe: Recipe, quantity_overrides: dict[int, float] | None = None
) -> RecipeMacros:
    """Calculate total macros for a recipe from its ingredients' nutrition data.

    Each ingredient's per-base-unit macros are scaled by
    ``quantity / nutrition_base_quantity`` and summed across the recipe.

    Args:
        recipe: The recipe to calculate. Its ``recipe_ingredients`` and each
            ingredient's ``ingredient`` relationship must be loadable.
        quantity_overrides: Optional mapping of ``RecipeIngredient.id`` to the
            quantity actually used. Ingredients absent from the mapping use
            the recipe's stated quantity. Keyed by RecipeIngredient rather
            than Ingredient so a recipe listing the same ingredient twice
            stays unambiguous.

    Returns:
        The summed macros as a RecipeMacros tuple.
    """
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
