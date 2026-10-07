from datetime import date, datetime

import pytest

from app.domain.recommendations import combine_scores, recommend_recipes
from app.errors import InvalidInputError
from app.persistence.enums import IngredientRole
from app.persistence.models import InventoryBatch, Recipe, RecipeIngredient

AS_OF = date(2026, 3, 10)
# Combined score of a fully stocked recipe with no dated ingredients (freshness 0).
FULL_AVAILABILITY_NO_FRESHNESS = 0.4 / 0.7


def make_recipe(name, *ingredients):
    """Build an unsaved Recipe from ingredient specs.

    Args:
        name: Recipe name, used to identify it in assertions.
        *ingredients: ``(ingredient_id, quantity, role)`` tuples, one per RecipeIngredient.

    Returns:
        A new, unpersisted Recipe with its RecipeIngredients attached.
    """
    return Recipe(
        name=name,
        instructions=[],
        prep_minutes=10,
        servings=1,
        recipe_ingredients=[
            RecipeIngredient(ingredient_id=ingredient_id, quantity=quantity, role=role)
            for ingredient_id, quantity, role in ingredients
        ],
    )


def make_batch(ingredient_id, quantity_remaining, use_by_date=None):
    """Build an unsaved InventoryBatch with the given remaining quantity.

    Args:
        ingredient_id: Ingredient the batch belongs to.
        quantity_remaining: Quantity still in the batch.
        use_by_date: Optional use-by date.

    Returns:
        A new, unpersisted InventoryBatch.
    """
    return InventoryBatch(
        ingredient_id=ingredient_id,
        quantity_initial=quantity_remaining,
        quantity_remaining=quantity_remaining,
        purchased_at=datetime(2026, 1, 1),
        use_by_date=use_by_date,
    )


def test_combine_scores_with_one_component_returns_that_score():
    """With a single component, the combined score is that component's score."""
    assert combine_scores({"availability": 0.7}) == pytest.approx(0.7)


def test_combine_scores_rescales_weights_of_present_components():
    """Weights of the components present are rescaled to sum to 1."""
    combined = combine_scores({"availability": 1.0, "freshness": 0.0})

    assert combined == pytest.approx(0.4 / 0.7)


def test_recipes_are_ranked_by_score_highest_first():
    """A fully stocked recipe ranks above a partially stocked one."""
    partial = make_recipe("Partial", (1, 200, IngredientRole.PRIMARY))
    full = make_recipe("Full", (2, 100, IngredientRole.PRIMARY))

    recommendations = recommend_recipes(
        [partial, full], [make_batch(1, 100), make_batch(2, 100)], AS_OF
    )

    assert [r.recipe.name for r in recommendations] == ["Full", "Partial"]
    assert recommendations[1].score == pytest.approx(0.5 * FULL_AVAILABILITY_NO_FRESHNESS)


def test_ineligible_recipes_are_excluded():
    """A recipe missing more than one PRIMARY ingredient is left out of the results."""
    ineligible = make_recipe(
        "Two Primaries Missing", (1, 200, IngredientRole.PRIMARY), (2, 100, IngredientRole.PRIMARY)
    )
    eligible = make_recipe("Stocked", (3, 100, IngredientRole.PRIMARY))

    recommendations = recommend_recipes([ineligible, eligible], [make_batch(3, 100)], AS_OF)

    assert [r.recipe.name for r in recommendations] == ["Stocked"]


def test_batches_of_the_same_ingredient_are_combined():
    """Availability uses total inventory across batches, not a single batch."""
    recipe = make_recipe("Chicken", (1, 200, IngredientRole.PRIMARY))

    recommendations = recommend_recipes(
        [recipe], [make_batch(1, 120), make_batch(1, 80)], AS_OF
    )

    assert recommendations[0].score == pytest.approx(FULL_AVAILABILITY_NO_FRESHNESS)


def test_freshness_ranks_recipe_using_expiring_ingredient_higher():
    """Between two fully stocked recipes, the one using an expiring ingredient ranks first."""
    keeps = make_recipe("Keeps", (1, 100, IngredientRole.PRIMARY))
    expiring = make_recipe("Expiring", (2, 100, IngredientRole.PRIMARY))
    batches = [make_batch(1, 100), make_batch(2, 100, use_by_date=date(2026, 3, 11))]

    recommendations = recommend_recipes([keeps, expiring], batches, AS_OF)

    assert [r.recipe.name for r in recommendations] == ["Expiring", "Keeps"]


def test_recommendation_carries_expired_batch_warnings():
    """Expired batches are surfaced on the recommendation without raising its score."""
    recipe = make_recipe("Leftovers", (1, 100, IngredientRole.PRIMARY))
    expired = make_batch(1, 100, use_by_date=date(2026, 3, 1))

    recommendation = recommend_recipes([recipe], [expired], AS_OF)[0]

    assert recommendation.freshness.expired_batches == [expired]
    assert recommendation.score == pytest.approx(FULL_AVAILABILITY_NO_FRESHNESS)


def test_datetime_as_of_is_rejected():
    """Recommendations require a calendar date, not a datetime."""
    with pytest.raises(InvalidInputError):
        recommend_recipes([], [], datetime(2026, 3, 10))
