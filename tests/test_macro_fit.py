from datetime import datetime

import pytest

from app.domain.macro_fit import (
    _carbs_score,
    _protein_score,
    _stay_under_score,
    assess_macro_fit,
)
from app.domain.nutrition_state import RemainingMacros
from app.errors import InvalidInputError
from app.persistence.enums import CanonicalUnit, IngredientRole
from app.persistence.models import Ingredient, Recipe, RecipeIngredient


def make_chicken_recipe(quantity=400, servings=2):
    """Build an unsaved chicken recipe with nutrition data attached.

    Chicken breast is 165 kcal, 31 g protein, 0 g carbs, and 3.6 g fat per 100 g.

    Args:
        quantity: Grams of chicken in the whole recipe.
        servings: Number of servings the recipe makes.

    Returns:
        A new, unpersisted Recipe.
    """
    chicken = Ingredient(
        name="Chicken Breast",
        canonical_unit=CanonicalUnit.GRAM,
        nutrition_base_quantity=100,
        calories_per_base_unit=165,
        protein_per_base_unit=31,
        carbs_per_base_unit=0,
        fat_per_base_unit=3.6,
        nutrition_updated_at=datetime(2026, 1, 1),
    )
    return Recipe(
        name="Grilled Chicken",
        instructions=[],
        prep_minutes=20,
        servings=servings,
        recipe_ingredients=[
            RecipeIngredient(ingredient=chicken, quantity=quantity, role=IngredientRole.PRIMARY),
        ],
    )


@pytest.mark.parametrize(
    ("serving", "remaining", "expected"),
    [
        (100, 300, 1.0),
        (300, 300, 1.0),
        (600, 300, 0.5),
        (100, 0, 0.0),
        (100, -50, 0.0),
        (0, -50, 1.0),
    ],
)
def test_stay_under_score(serving, remaining, expected):
    """A serving that fits scores 1.0; otherwise it scores the share that fits."""
    assert _stay_under_score(serving, remaining) == pytest.approx(expected)


@pytest.mark.parametrize(
    ("serving", "remaining", "expected"),
    [
        (30, 60, 0.5),
        (60, 60, 1.0),
        (90, 60, 1.0),
        (135, 60, 0.5),
        (180, 60, 0.0),
        (240, 60, 0.0),
        (10, 0, 1.0),
        (10, -5, 1.0),
    ],
)
def test_protein_score(serving, remaining, expected):
    """Protein rewards coverage, tolerates excess to 1.5x, and reaches 0 at 3x the target."""
    assert _protein_score(serving, remaining) == pytest.approx(expected)


@pytest.mark.parametrize(
    ("serving", "remaining", "expected"),
    [
        (50, 100, 1.0),
        (25, 100, 1.0),
        (10, 100, 0.7),
        (0, 100, 0.5),
        (150, 100, 100 / 150),
        (20, 0, 0.0),
        (0, 0, 1.0),
    ],
)
def test_carbs_score(serving, remaining, expected):
    """Carbs score 1.0 from 25% to 100% of the remaining target, less outside that range."""
    assert _carbs_score(serving, remaining) == pytest.approx(expected)


def test_macros_are_measured_per_serving():
    """The recipe's total macros are divided by its servings."""
    remaining = RemainingMacros(calories=2000, protein=150, carbs=200, fat=70)

    fit = assess_macro_fit(make_chicken_recipe(quantity=400, servings=2), remaining)

    assert fit.per_serving.calories == pytest.approx(330)
    assert fit.per_serving.protein == pytest.approx(62)
    assert fit.per_serving.fat == pytest.approx(7.2)


def test_macro_scores_combine_by_priority_weights():
    """Calories 0.4, protein 0.3, fat 0.2, carbs 0.1 combine into the macro-fit score."""
    # Per serving: 330 kcal fits, 62 g protein covers the 50 g left, 7.2 g fat fits,
    # and 0 g carbs against 200 g left scores 0.5.
    remaining = RemainingMacros(calories=2000, protein=50, carbs=200, fat=70)

    fit = assess_macro_fit(make_chicken_recipe(), remaining)

    assert fit.score == pytest.approx(0.4 + 0.3 + 0.2 + 0.1 * 0.5)


def test_over_budget_serving_lowers_the_score():
    """A serving with twice the remaining calories loses half the calorie weight."""
    remaining = RemainingMacros(calories=165, protein=0, carbs=0, fat=70)

    fit = assess_macro_fit(make_chicken_recipe(), remaining)

    assert fit.score == pytest.approx(0.4 * 0.5 + 0.3 + 0.2 + 0.1)


def test_non_positive_servings_are_rejected():
    """A recipe with zero servings raises instead of dividing by zero."""
    remaining = RemainingMacros(calories=2000, protein=150, carbs=200, fat=70)

    with pytest.raises(InvalidInputError):
        assess_macro_fit(make_chicken_recipe(servings=0), remaining)
