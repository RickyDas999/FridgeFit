from typing import NamedTuple

from app.domain.validation import validate_recipe
from app.persistence.enums import IngredientRole
from app.persistence.models import Recipe, RecipeIngredient

ROLE_WEIGHTS = {
    IngredientRole.PRIMARY: 3,
    IngredientRole.SUPPORTING: 2,
    IngredientRole.OPTIONAL: 1,
}


class IngredientAvailability(NamedTuple):
    """How much of one recipe ingredient is on hand."""

    recipe_ingredient: RecipeIngredient
    quantity_on_hand: float
    fraction_available: float

    @property
    def is_missing(self) -> bool:
        """Whether none of the ingredient is on hand.

        Partial amounts are not missing; their shortfall shows in ``fraction_available``.

        Returns:
            True if ``fraction_available`` is zero.
        """
        return self.fraction_available == 0


class RecipeAvailability(NamedTuple):
    """Availability assessment for a whole recipe."""

    ingredients: list[IngredientAvailability]
    score: float
    is_eligible: bool


def assess_recipe_availability(
    recipe: Recipe, inventory_totals: dict[int, float]
) -> RecipeAvailability:
    """Assess how much of one serving of a recipe can be made from current inventory.

    Recommendations describe cooking one serving, so each ingredient is judged against its
    per-serving quantity (``quantity / recipe.servings``). The score is the average of each
    ingredient's fraction on hand (capped at 1), weighted by role importance. A recipe is
    ineligible when more than one PRIMARY ingredient is missing; missing SUPPORTING or OPTIONAL
    ingredients only lower the score.

    Args:
        recipe: The recipe to assess. Its ``recipe_ingredients`` must be loadable.
        inventory_totals: Mapping of ``ingredient_id`` to total quantity on hand, as returned
            by ``aggregate_inventory_by_ingredient``.

    Returns:
        Per-ingredient availability, the 0-1 availability score, and eligibility.

    Raises:
        InvalidInputError: If the recipe has no ingredients, a non-positive quantity, or
            non-positive servings.
    """
    validate_recipe(recipe)

    ingredients = []
    for recipe_ingredient in recipe.recipe_ingredients:
        on_hand = inventory_totals.get(recipe_ingredient.ingredient_id, 0.0)
        per_serving = recipe_ingredient.quantity
        if recipe_ingredient.role == IngredientRole.PRIMARY:
            per_serving /= recipe.servings
        fraction = min(on_hand / per_serving, 1.0)
        ingredients.append(IngredientAvailability(recipe_ingredient, on_hand, fraction))

    total_weight = sum(ROLE_WEIGHTS[i.recipe_ingredient.role] for i in ingredients)
    score = sum(
        ROLE_WEIGHTS[i.recipe_ingredient.role] * i.fraction_available for i in ingredients
    ) / total_weight

    missing_primary = sum(
        1
        for i in ingredients
        if i.is_missing and i.recipe_ingredient.role == IngredientRole.PRIMARY
    )

    return RecipeAvailability(
        ingredients=ingredients, score=score, is_eligible=missing_primary <= 1
    )
