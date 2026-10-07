from datetime import datetime

import pytest

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
    ingredient = make_ingredient()
    recipe = make_recipe()
    session.add_all([ingredient, recipe])
    session.commit()

    session.add(RecipeIngredient(
        recipe_id=recipe.id,
        ingredient_id=ingredient.id,
        quantity=200,
        role=IngredientRole.PRIMARY,
    ))
    session.commit()
    session.refresh(recipe)

    macros = calculate_recipe_macros(recipe)

    assert macros.calories == pytest.approx(330)
    assert macros.protein == pytest.approx(62)
    assert macros.carbs == pytest.approx(0)
    assert macros.fat == pytest.approx(7.2)


def test_macros_sum_across_multiple_recipe_ingredients(session):
    """Macros from every RecipeIngredient are summed."""
    chicken = make_ingredient()
    rice = make_ingredient(
        name="Rice",
        calories_per_base_unit=130,
        protein_per_base_unit=2.7,
        carbs_per_base_unit=28,
        fat_per_base_unit=0.3,
    )
    recipe = make_recipe()
    session.add_all([chicken, rice, recipe])
    session.commit()

    session.add_all([
        RecipeIngredient(
            recipe_id=recipe.id,
            ingredient_id=chicken.id,
            quantity=200,
            role=IngredientRole.PRIMARY,
        ),
        RecipeIngredient(
            recipe_id=recipe.id,
            ingredient_id=rice.id,
            quantity=150,
            role=IngredientRole.SUPPORTING,
        ),
    ])
    session.commit()
    session.refresh(recipe)

    macros = calculate_recipe_macros(recipe)

    assert macros.calories == pytest.approx(330 + 195)
    assert macros.protein == pytest.approx(62 + 4.05)
    assert macros.carbs == pytest.approx(0 + 42)
    assert macros.fat == pytest.approx(7.2 + 0.45)


def test_macros_are_zero_for_recipe_with_no_ingredients(session):
    """A recipe with no ingredients has zero macros."""
    recipe = make_recipe()
    session.add(recipe)
    session.commit()
    session.refresh(recipe)

    macros = calculate_recipe_macros(recipe)

    assert macros == (0, 0, 0, 0)


def test_quantity_override_scales_macros_for_that_ingredient(session):
    """A quantity override replaces the recipe quantity in the calculation."""
    ingredient = make_ingredient()
    recipe = make_recipe()
    session.add_all([ingredient, recipe])
    session.commit()

    recipe_ingredient = RecipeIngredient(
        recipe_id=recipe.id, ingredient_id=ingredient.id, quantity=200, role=IngredientRole.PRIMARY
    )
    session.add(recipe_ingredient)
    session.commit()
    session.refresh(recipe)

    macros = calculate_recipe_macros(recipe, quantity_overrides={recipe_ingredient.id: 150})

    assert macros.calories == pytest.approx(165 * 1.5)
    assert macros.protein == pytest.approx(31 * 1.5)


def test_quantity_override_defaults_to_recipe_quantity_when_absent(session):
    """Ingredients missing from the override map use the recipe quantity."""
    ingredient = make_ingredient()
    recipe = make_recipe()
    session.add_all([ingredient, recipe])
    session.commit()

    session.add(RecipeIngredient(
        recipe_id=recipe.id,
        ingredient_id=ingredient.id,
        quantity=200,
        role=IngredientRole.PRIMARY,
    ))
    session.commit()
    session.refresh(recipe)

    macros = calculate_recipe_macros(recipe, quantity_overrides={})

    assert macros.calories == pytest.approx(330)
