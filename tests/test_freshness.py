from datetime import date, datetime, timedelta

import pytest

from app.domain.freshness import assess_recipe_freshness
from app.errors import InvalidInputError
from app.persistence.enums import IngredientRole
from app.persistence.models import InventoryBatch, Recipe, RecipeIngredient

AS_OF = date(2026, 3, 10)


def make_recipe(*ingredient_ids):
    """Build an unsaved Recipe with one PRIMARY RecipeIngredient per ingredient id.

    Args:
        *ingredient_ids: Ingredient ids to include in the recipe.

    Returns:
        A new, unpersisted Recipe with its RecipeIngredients attached.
    """
    return Recipe(
        name="Test Recipe",
        instructions=[],
        prep_minutes=10,
        servings=1,
        recipe_ingredients=[
            RecipeIngredient(ingredient_id=i, quantity=100, role=IngredientRole.PRIMARY)
            for i in ingredient_ids
        ],
    )


def make_batch(ingredient_id, days_until_use_by, quantity_remaining=100):
    """Build an unsaved InventoryBatch whose use-by date is relative to ``AS_OF``.

    Args:
        ingredient_id: Ingredient the batch belongs to.
        days_until_use_by: Days from ``AS_OF`` to the use-by date (negative means expired),
            or None for an undated batch.
        quantity_remaining: Quantity still in the batch.

    Returns:
        A new, unpersisted InventoryBatch.
    """
    use_by = None if days_until_use_by is None else AS_OF + timedelta(days=days_until_use_by)
    return InventoryBatch(
        ingredient_id=ingredient_id,
        quantity_initial=max(quantity_remaining, 1),
        quantity_remaining=quantity_remaining,
        purchased_at=datetime(2026, 1, 1),
        use_by_date=use_by,
    )


def assess(recipe, *batches):
    """Assess a recipe's freshness against the given batches as of ``AS_OF``.

    Args:
        recipe: The recipe to assess.
        *batches: Inventory batches, grouped by ingredient before assessment.

    Returns:
        The RecipeFreshness result.
    """
    batches_by_ingredient = {}
    for batch in batches:
        batches_by_ingredient.setdefault(batch.ingredient_id, []).append(batch)
    return assess_recipe_freshness(recipe, batches_by_ingredient, AS_OF)


def test_recipe_with_no_dated_ingredients_scores_zero():
    """Without any use-by dates there is nothing urgent to use up."""
    freshness = assess(make_recipe(1), make_batch(1, None))

    assert freshness.score == 0.0
    assert freshness.expired_batches == []


@pytest.mark.parametrize(
    ("days", "expected"),
    [(0, 1.0), (1, 6 / 7), (2, 5 / 7), (5, 2 / 7), (7, 0.0), (30, 0.0)],
)
def test_score_falls_linearly_from_today_to_seven_days(days, expected):
    """The most urgent ingredient scores 1.0 today and reaches 0 at seven days out."""
    freshness = assess(make_recipe(1), make_batch(1, days))

    assert freshness.score == pytest.approx(expected)


def test_ingredients_further_out_do_not_add_to_the_score():
    """Only ingredients due within two days earn a bonus beyond the most urgent one."""
    freshness = assess(make_recipe(1, 2), make_batch(1, 1), make_batch(2, 5))

    assert freshness.score == pytest.approx(6 / 7)


def test_each_additional_expiring_soon_ingredient_adds_a_bonus():
    """A second ingredient due within two days adds 0.1."""
    freshness = assess(make_recipe(1, 2), make_batch(1, 2), make_batch(2, 2))

    assert freshness.score == pytest.approx(5 / 7 + 0.1)


def test_bonus_is_capped_at_one():
    """The score never exceeds 1.0, however many ingredients are expiring soon."""
    freshness = assess(
        make_recipe(1, 2, 3), make_batch(1, 0), make_batch(2, 1), make_batch(3, 1)
    )

    assert freshness.score == 1.0


def test_earliest_batch_of_an_ingredient_sets_its_urgency():
    """An ingredient is as urgent as its soonest-dated batch."""
    freshness = assess(make_recipe(1), make_batch(1, 6), make_batch(1, 1))

    assert freshness.score == pytest.approx(6 / 7)


def test_expired_batch_is_a_warning_and_does_not_boost_the_score():
    """Expired stock is reported but never makes a recipe rank as more urgent."""
    expired = make_batch(1, -3)

    freshness = assess(make_recipe(1), expired, make_batch(1, 4))

    assert freshness.expired_batches == [expired]
    assert freshness.score == pytest.approx(3 / 7)


def test_use_by_date_today_is_not_expired():
    """A batch whose use-by date is today is still usable, and maximally urgent."""
    freshness = assess(make_recipe(1), make_batch(1, 0))

    assert freshness.expired_batches == []
    assert freshness.score == 1.0


def test_empty_batches_are_ignored():
    """A batch with nothing left neither sets urgency nor triggers a warning."""
    freshness = assess(
        make_recipe(1),
        make_batch(1, 0, quantity_remaining=0),
        make_batch(1, -2, quantity_remaining=0),
    )

    assert freshness.score == 0.0
    assert freshness.expired_batches == []


def test_batches_for_other_ingredients_are_ignored():
    """Only the recipe's own ingredients affect its freshness."""
    freshness = assess(make_recipe(1), make_batch(1, None), make_batch(2, 0), make_batch(2, -1))

    assert freshness.score == 0.0
    assert freshness.expired_batches == []


def test_datetime_as_of_is_rejected():
    """Freshness requires a calendar date, not a datetime."""
    with pytest.raises(InvalidInputError):
        assess_recipe_freshness(make_recipe(1), {}, datetime(2026, 3, 10))
