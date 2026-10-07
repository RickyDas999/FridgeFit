from datetime import date, datetime
from typing import Sequence

from app.errors import InvalidInputError
from app.persistence.models import InventoryBatch, Recipe


def validate_recipe(recipe: Recipe) -> None:
    """Check that a recipe has ingredients and that every ingredient quantity is positive.

    Args:
        recipe: The recipe to check. Its ``recipe_ingredients`` must be loadable.

    Raises:
        InvalidInputError: If the recipe has no ingredients or any quantity is not positive.
    """
    if not recipe.recipe_ingredients:
        raise InvalidInputError(f"Recipe {recipe.name!r} has no ingredients")
    for recipe_ingredient in recipe.recipe_ingredients:
        if recipe_ingredient.quantity <= 0:
            raise InvalidInputError(
                f"Recipe {recipe.name!r} has a non-positive quantity "
                f"({recipe_ingredient.quantity}) for ingredient {recipe_ingredient.ingredient_id}"
            )


def validate_nutrition_base_quantities(recipe: Recipe) -> None:
    """Check that every ingredient in a recipe has a positive nutrition base quantity.

    Args:
        recipe: The recipe whose ingredients to check. Each RecipeIngredient's ``ingredient``
            must be loadable.

    Raises:
        InvalidInputError: If any ingredient's nutrition base quantity is not positive.
    """
    for recipe_ingredient in recipe.recipe_ingredients:
        ingredient = recipe_ingredient.ingredient
        if ingredient.nutrition_base_quantity <= 0:
            raise InvalidInputError(
                f"Ingredient {ingredient.name!r} has a non-positive nutrition base quantity "
                f"({ingredient.nutrition_base_quantity})"
            )


def validate_quantity_overrides(recipe: Recipe, quantity_overrides: dict[int, float]) -> None:
    """Check that quantity overrides refer to this recipe's ingredients and are not negative.

    Zero is allowed: it means none of that ingredient was actually used.

    Args:
        recipe: The recipe the overrides apply to.
        quantity_overrides: Mapping of ``RecipeIngredient.id`` to the quantity actually used.

    Raises:
        InvalidInputError: If a key is not one of the recipe's RecipeIngredient ids, or a value
            is negative.
    """
    recipe_ingredient_ids = {ri.id for ri in recipe.recipe_ingredients}
    for recipe_ingredient_id, quantity in quantity_overrides.items():
        if recipe_ingredient_id not in recipe_ingredient_ids:
            raise InvalidInputError(
                f"Quantity override for RecipeIngredient {recipe_ingredient_id}, "
                f"which is not part of recipe {recipe.name!r}"
            )
        if quantity < 0:
            raise InvalidInputError(
                f"Quantity override for RecipeIngredient {recipe_ingredient_id} is negative "
                f"({quantity})"
            )


def validate_quantity_needed(quantity_needed: float) -> None:
    """Check that a requested consumption quantity is positive.

    Args:
        quantity_needed: The quantity to consume.

    Raises:
        InvalidInputError: If the quantity is not positive.
    """
    if quantity_needed <= 0:
        raise InvalidInputError(f"Quantity needed must be positive, got {quantity_needed}")


def validate_single_ingredient_batches(batches: Sequence[InventoryBatch]) -> None:
    """Check that all batches belong to the same ingredient.

    Args:
        batches: The batches to check. An empty sequence is valid.

    Raises:
        InvalidInputError: If the batches span more than one ingredient.
    """
    ingredient_ids = {batch.ingredient_id for batch in batches}
    if len(ingredient_ids) > 1:
        raise InvalidInputError(
            f"Batches must belong to a single ingredient, got ingredients {sorted(ingredient_ids)}"
        )


def validate_calendar_date(as_of: date) -> None:
    """Check that a value is a calendar date and not a datetime.

    ``datetime`` subclasses ``date``, so a datetime would otherwise pass type checks while
    never comparing equal to a meal's consumption date.

    Args:
        as_of: The value to check.

    Raises:
        InvalidInputError: If the value is a datetime or not a date at all.
    """
    if isinstance(as_of, datetime) or not isinstance(as_of, date):
        raise InvalidInputError(f"Expected a calendar date, got {as_of!r}")
