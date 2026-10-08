from datetime import date, datetime

import pytest

from app.domain.nutrition_state import RemainingMacros
from app.domain.recommendations import combine_scores, recommend_recipes
from app.errors import InvalidInputError
from app.persistence.enums import CanonicalUnit, IngredientRole
from app.persistence.models import (
    Ingredient,
    InventoryBatch,
    MealFeedback,
    MealLog,
    Recipe,
    RecipeIngredient,
)

AS_OF = date(2026, 3, 10)

def expected_score(availability, expiry_urgency=0.0, enjoyment=0.5):
    """Combined score with no nutrition goal, so macro fit is left out and weights rescale.

    Args:
        availability: Availability score.
        expiry_urgency: Expiry urgency score; 0 when no ingredient is dated.
        enjoyment: Enjoyment score; 0.5 for an unrated recipe.

    Returns:
        The weighted combined score.
    """
    return (0.4 * availability + 0.3 * expiry_urgency + 0.1 * enjoyment) / 0.8


# A fully stocked, undated, unrated recipe with no nutrition goal.
FULL_STOCK_SCORE = expected_score(availability=1.0)


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
    combined = combine_scores({"availability": 1.0, "expiry_urgency": 0.0})

    assert combined == pytest.approx(0.4 / 0.7)


def test_recipes_are_ranked_by_score_highest_first():
    """A fully stocked recipe ranks above a partially stocked one."""
    partial = make_recipe("Partial", (1, 200, IngredientRole.PRIMARY))
    full = make_recipe("Full", (2, 100, IngredientRole.PRIMARY))

    recommendations = recommend_recipes(
        [partial, full], [make_batch(1, 100), make_batch(2, 100)], AS_OF, None, [], []
    )

    assert [r.recipe.name for r in recommendations] == ["Full", "Partial"]
    assert recommendations[1].score == pytest.approx(expected_score(availability=0.5))


def test_ineligible_recipes_are_excluded():
    """A recipe missing more than one PRIMARY ingredient is left out of the results."""
    ineligible = make_recipe(
        "Two Primaries Missing", (1, 200, IngredientRole.PRIMARY), (2, 100, IngredientRole.PRIMARY)
    )
    eligible = make_recipe("Stocked", (3, 100, IngredientRole.PRIMARY))

    recommendations = recommend_recipes(
        [ineligible, eligible], [make_batch(3, 100)], AS_OF, None, [], []
    )

    assert [r.recipe.name for r in recommendations] == ["Stocked"]


def test_batches_of_the_same_ingredient_are_combined():
    """Availability uses total inventory across batches, not a single batch."""
    recipe = make_recipe("Chicken", (1, 200, IngredientRole.PRIMARY))

    recommendations = recommend_recipes(
        [recipe], [make_batch(1, 120), make_batch(1, 80)], AS_OF, None, [], []
    )

    assert recommendations[0].score == pytest.approx(FULL_STOCK_SCORE)


def test_expiry_urgency_ranks_recipe_using_expiring_ingredient_higher():
    """Between two fully stocked recipes, the one using an expiring ingredient ranks first."""
    keeps = make_recipe("Keeps", (1, 100, IngredientRole.PRIMARY))
    expiring = make_recipe("Expiring", (2, 100, IngredientRole.PRIMARY))
    batches = [make_batch(1, 100), make_batch(2, 100, use_by_date=date(2026, 3, 11))]

    recommendations = recommend_recipes([keeps, expiring], batches, AS_OF, None, [], [])

    assert [r.recipe.name for r in recommendations] == ["Expiring", "Keeps"]


def test_recommendation_carries_expired_batch_warnings():
    """Expired batches are surfaced on the recommendation without raising its score."""
    recipe = make_recipe("Leftovers", (1, 100, IngredientRole.PRIMARY))
    expired = make_batch(1, 100, use_by_date=date(2026, 3, 1))

    recommendation = recommend_recipes([recipe], [expired], AS_OF, None, [], [])[0]

    assert recommendation.expiry_urgency.expired_batches == [expired]
    assert recommendation.score == pytest.approx(FULL_STOCK_SCORE)


def test_datetime_as_of_is_rejected():
    """Recommendations require a calendar date, not a datetime."""
    with pytest.raises(InvalidInputError):
        recommend_recipes([], [], datetime(2026, 3, 10), None, [], [])


def make_single_ingredient_recipe(name, ingredient_id, calories_per_100g):
    """Build an unsaved one-serving recipe of 100 g of one ingredient, with nutrition attached.

    Args:
        name: Recipe name, used to identify it in assertions.
        ingredient_id: Id given to the ingredient, used to match inventory batches.
        calories_per_100g: Calories in the ingredient; other macros are zero.

    Returns:
        A new, unpersisted Recipe.
    """
    ingredient = Ingredient(
        id=ingredient_id,
        name=name,
        canonical_unit=CanonicalUnit.GRAM,
        nutrition_base_quantity=100,
        calories_per_base_unit=calories_per_100g,
        protein_per_base_unit=0,
        carbs_per_base_unit=0,
        fat_per_base_unit=0,
        nutrition_updated_at=datetime(2026, 1, 1),
    )
    return Recipe(
        name=name,
        instructions=[],
        prep_minutes=10,
        servings=1,
        recipe_ingredients=[
            RecipeIngredient(
                ingredient_id=ingredient_id,
                ingredient=ingredient,
                quantity=100,
                role=IngredientRole.PRIMARY,
            ),
        ],
    )


def test_macro_fit_ranks_recipe_within_calorie_budget_higher():
    """All else equal, the recipe that fits the calorie budget ranks first."""
    light = make_single_ingredient_recipe("Light", 1, calories_per_100g=200)
    heavy = make_single_ingredient_recipe("Heavy", 2, calories_per_100g=800)
    remaining = RemainingMacros(calories=400, protein=0, carbs=0, fat=0)

    recommendations = recommend_recipes(
        [heavy, light], [make_batch(1, 100), make_batch(2, 100)], AS_OF, remaining, [], []
    )

    assert [r.recipe.name for r in recommendations] == ["Light", "Heavy"]
    assert recommendations[0].macro_fit.score == pytest.approx(1.0)


def test_macro_fit_is_left_out_without_a_nutrition_goal():
    """With no remaining macros, macro fit is skipped and the other weights rescale."""
    recipe = make_single_ingredient_recipe("Light", 1, calories_per_100g=200)

    recommendation = recommend_recipes([recipe], [make_batch(1, 100)], AS_OF, None, [], [])[0]

    assert recommendation.macro_fit is None
    assert recommendation.score == pytest.approx(FULL_STOCK_SCORE)


def test_enjoyment_ranks_well_liked_recipe_higher():
    """All else equal, a recipe rated 5 ranks above an unrated one."""
    unrated = make_recipe("Unrated", (1, 100, IngredientRole.PRIMARY))
    favorite = make_recipe("Favorite", (2, 100, IngredientRole.PRIMARY))
    unrated.id, favorite.id = 1, 2
    feedback = [MealFeedback(rating=5, meal_log=MealLog(recipe_id=2))]

    recommendations = recommend_recipes(
        [unrated, favorite], [make_batch(1, 100), make_batch(2, 100)], AS_OF, None, feedback, []
    )

    assert [r.recipe.name for r in recommendations] == ["Favorite", "Unrated"]
    favorite_score = expected_score(availability=1.0, enjoyment=1.0)
    assert recommendations[0].score == pytest.approx(favorite_score)
    assert recommendations[1].enjoyment.score == 0.5


def test_recent_frequency_is_reported_but_never_changes_the_score():
    """A recipe eaten often scores the same as an identical uneaten one."""
    often = make_recipe("Often", (1, 100, IngredientRole.PRIMARY))
    never = make_recipe("Never", (2, 100, IngredientRole.PRIMARY))
    often.id, never.id = 1, 2
    meal_logs = [
        MealLog(recipe_id=1, consumed_at=datetime(2026, 3, day, 12)) for day in (8, 9, 10)
    ]

    recommendations = recommend_recipes(
        [often, never], [make_batch(1, 100), make_batch(2, 100)], AS_OF, None, [], meal_logs
    )

    by_name = {r.recipe.name: r for r in recommendations}
    assert by_name["Often"].score == pytest.approx(by_name["Never"].score)
    assert by_name["Often"].recent_frequency.times_eaten_recently == 3
    assert by_name["Often"].recent_frequency.last_eaten_on == date(2026, 3, 10)
    assert by_name["Never"].recent_frequency.times_eaten_recently == 0
