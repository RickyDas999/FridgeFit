import pytest

from app.domain.availability import assess_recipe_availability
from app.errors import InvalidInputError
from app.persistence.enums import IngredientRole
from app.persistence.models import Recipe, RecipeIngredient

PRIMARY = IngredientRole.PRIMARY
SUPPORTING = IngredientRole.SUPPORTING
OPTIONAL = IngredientRole.OPTIONAL


def make_recipe(*ingredients):
    """Build an unsaved Recipe from ingredient specs.

    Args:
        *ingredients: ``(ingredient_id, quantity, role)`` tuples, one per RecipeIngredient.

    Returns:
        A new, unpersisted Recipe with its RecipeIngredients attached.
    """
    return Recipe(
        name="Test Recipe",
        instructions=[],
        prep_minutes=10,
        servings=1,
        recipe_ingredients=[
            RecipeIngredient(ingredient_id=ingredient_id, quantity=quantity, role=role)
            for ingredient_id, quantity, role in ingredients
        ],
    )


def test_fully_stocked_recipe_scores_one():
    """A recipe with every ingredient fully on hand scores 1 and has nothing missing."""
    recipe = make_recipe((1, 200, PRIMARY), (2, 100, SUPPORTING))

    availability = assess_recipe_availability(recipe, {1: 500, 2: 100})

    assert availability.score == pytest.approx(1.0)
    assert availability.is_eligible
    assert not any(i.is_missing for i in availability.ingredients)


def test_surplus_inventory_is_capped_at_full_availability():
    """Having more than needed counts as fully available, not more."""
    recipe = make_recipe((1, 200, PRIMARY))

    availability = assess_recipe_availability(recipe, {1: 1000})

    assert availability.ingredients[0].fraction_available == 1.0


def test_partial_amount_is_not_missing_but_reports_shortfall():
    """A partial amount on hand is available, with its fraction reported."""
    recipe = make_recipe((1, 220, PRIMARY), (2, 100, SUPPORTING))

    availability = assess_recipe_availability(recipe, {1: 150, 2: 100})

    chicken = availability.ingredients[0]
    assert not chicken.is_missing
    assert chicken.quantity_on_hand == 150
    assert chicken.fraction_available == pytest.approx(150 / 220)
    assert availability.score == pytest.approx((3 * (150 / 220) + 2 * 1.0) / 5)


def test_role_weights_make_primary_shortfalls_cost_more():
    """The same shortfall lowers the score more on a PRIMARY than an OPTIONAL ingredient."""
    short_primary = make_recipe((1, 100, PRIMARY), (2, 100, OPTIONAL))
    short_optional = make_recipe((1, 100, OPTIONAL), (2, 100, PRIMARY))
    inventory = {1: 50, 2: 100}

    primary_score = assess_recipe_availability(short_primary, inventory).score
    optional_score = assess_recipe_availability(short_optional, inventory).score

    assert primary_score < optional_score


def test_one_missing_primary_ingredient_is_still_eligible():
    """A recipe missing exactly one PRIMARY ingredient may still be recommended."""
    recipe = make_recipe((1, 200, PRIMARY), (2, 100, PRIMARY))

    availability = assess_recipe_availability(recipe, {2: 100})

    assert availability.is_eligible
    assert availability.ingredients[0].is_missing


def test_two_missing_primary_ingredients_are_ineligible():
    """A recipe missing more than one PRIMARY ingredient is excluded."""
    recipe = make_recipe((1, 200, PRIMARY), (2, 100, PRIMARY), (3, 50, SUPPORTING))

    availability = assess_recipe_availability(recipe, {3: 50})

    assert not availability.is_eligible


def test_missing_supporting_and_optional_ingredients_never_exclude():
    """Missing non-PRIMARY ingredients lower the score but never make a recipe ineligible."""
    recipe = make_recipe(
        (1, 200, PRIMARY), (2, 100, SUPPORTING), (3, 100, SUPPORTING), (4, 10, OPTIONAL)
    )

    availability = assess_recipe_availability(recipe, {1: 200})

    assert availability.is_eligible
    assert availability.score == pytest.approx(3 / 8)


def test_recipe_with_no_ingredients_raises():
    """A recipe with no ingredients is invalid and is rejected rather than scored."""
    with pytest.raises(InvalidInputError):
        assess_recipe_availability(make_recipe(), {})


def test_non_positive_recipe_quantity_is_rejected():
    """A zero ingredient quantity raises instead of dividing by zero."""
    with pytest.raises(InvalidInputError):
        assess_recipe_availability(make_recipe((1, 0, PRIMARY)), {1: 100})
