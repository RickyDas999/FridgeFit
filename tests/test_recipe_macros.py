from datetime import datetime

import pytest

from app.errors import InvalidInputError
from app.persistence.enums import CanonicalUnit, IngredientRole
from app.persistence.models import Ingredient, Recipe, RecipeIngredient
from app.domain.recipe_macros import calculate_recipe_macros


def make_ingredient(**overrides):
    """Build an unsaved Ingredient with chicken-breast defaults.

    Args:
        **overrides: Ingredient field values that replace the defaults.

    Returns:
        A new, unpersisted Ingredient.
    """
    defaults = dict(
        name="Chicken Breast",
        canonical_unit=CanonicalUnit.GRAM,
        nutrition_base_quantity=100,
        calories_per_base_unit=165,
        protein_per_base_unit=31,
        carbs_per_base_unit=0,
        fat_per_base_unit=3.6,
        nutrition_updated_at=datetime(2026, 1, 1),
    )
    defaults.update(overrides)
    return Ingredient(**defaults)


def make_recipe(**overrides):
    """Build an unsaved Recipe with valid defaults.

    Args:
        **overrides: Recipe field values that replace the defaults.

    Returns:
        A new, unpersisted Recipe.
    """
    defaults = dict(
        name="Grilled Chicken Bowl",
        instructions=["Season chicken", "Grill 6 minutes per side"],
        prep_minutes=20,
        servings=2,
    )
    defaults.update(overrides)
    return Recipe(**defaults)


def test_macros_scale_with_quantity_relative_to_base(session):
    """Macros scale linearly with quantity relative to the nutrition base quantity."""
    recipe = make_recipe(recipe_ingredients=[
        RecipeIngredient(ingredient=make_ingredient(), quantity=200, role=IngredientRole.PRIMARY),
    ])
    session.add(recipe)
    session.commit()

    macros = calculate_recipe_macros(recipe)

    assert macros.calories == pytest.approx(330)
    assert macros.protein == pytest.approx(62)
    assert macros.carbs == pytest.approx(0)
    assert macros.fat == pytest.approx(7.2)


def test_macros_sum_across_multiple_recipe_ingredients(session):
    """Macros from every RecipeIngredient are summed."""
    rice = make_ingredient(
        name="Rice",
        calories_per_base_unit=130,
        protein_per_base_unit=2.7,
        carbs_per_base_unit=28,
        fat_per_base_unit=0.3,
    )
    recipe = make_recipe(recipe_ingredients=[
        RecipeIngredient(ingredient=make_ingredient(), quantity=200, role=IngredientRole.PRIMARY),
        RecipeIngredient(ingredient=rice, quantity=150, role=IngredientRole.SUPPORTING),
    ])
    session.add(recipe)
    session.commit()

    macros = calculate_recipe_macros(recipe)

    assert macros.calories == pytest.approx(330 + 195)
    assert macros.protein == pytest.approx(62 + 4.05)
    assert macros.carbs == pytest.approx(0 + 42)
    assert macros.fat == pytest.approx(7.2 + 0.45)


def test_quantity_override_scales_macros_for_that_ingredient(session):
    """A quantity override replaces the recipe quantity in the calculation."""
    recipe_ingredient = RecipeIngredient(
        ingredient=make_ingredient(), quantity=200, role=IngredientRole.PRIMARY
    )
    recipe = make_recipe(recipe_ingredients=[recipe_ingredient])
    session.add(recipe)
    session.commit()

    macros = calculate_recipe_macros(recipe, quantity_overrides={recipe_ingredient.id: 150})

    assert macros.calories == pytest.approx(165 * 1.5)
    assert macros.protein == pytest.approx(31 * 1.5)


def test_quantity_override_defaults_to_recipe_quantity_when_absent(session):
    """Ingredients missing from the override map use the recipe quantity."""
    recipe = make_recipe(recipe_ingredients=[
        RecipeIngredient(ingredient=make_ingredient(), quantity=200, role=IngredientRole.PRIMARY),
    ])
    session.add(recipe)
    session.commit()

    macros = calculate_recipe_macros(recipe, quantity_overrides={})

    assert macros.calories == pytest.approx(330)


def test_recipe_with_no_ingredients_is_rejected():
    """Macros are not calculated for a recipe with no ingredients."""
    with pytest.raises(InvalidInputError):
        calculate_recipe_macros(make_recipe())


def test_non_positive_nutrition_base_quantity_is_rejected():
    """An ingredient with a zero base quantity raises instead of dividing by zero."""
    recipe = make_recipe(recipe_ingredients=[
        RecipeIngredient(
            ingredient=make_ingredient(nutrition_base_quantity=0),
            quantity=200,
            role=IngredientRole.PRIMARY,
        ),
    ])

    with pytest.raises(InvalidInputError):
        calculate_recipe_macros(recipe)


def test_override_for_ingredient_outside_the_recipe_is_rejected(session):
    """An override keyed by a RecipeIngredient not in this recipe raises."""
    recipe_ingredient = RecipeIngredient(
        ingredient=make_ingredient(), quantity=200, role=IngredientRole.PRIMARY
    )
    recipe = make_recipe(recipe_ingredients=[recipe_ingredient])
    session.add(recipe)
    session.commit()

    with pytest.raises(InvalidInputError):
        calculate_recipe_macros(recipe, quantity_overrides={recipe_ingredient.id + 1: 150})


def test_negative_override_is_rejected(session):
    """A negative override quantity raises."""
    recipe_ingredient = RecipeIngredient(
        ingredient=make_ingredient(), quantity=200, role=IngredientRole.PRIMARY
    )
    recipe = make_recipe(recipe_ingredients=[recipe_ingredient])
    session.add(recipe)
    session.commit()

    with pytest.raises(InvalidInputError):
        calculate_recipe_macros(recipe, quantity_overrides={recipe_ingredient.id: -1})
