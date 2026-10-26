from datetime import date, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app.application.meal_planning import get_meal_plan
from app.domain.enjoyment import RatingSummary
from app.domain.meal_planning import SimulatedBatch, _tie_break_key, plan_meals
from app.domain.nutrition_state import RemainingMacros
from app.domain.recommendations import recommend_recipes
from app.errors import InvalidInputError
from app.persistence.enums import CanonicalUnit, IngredientRole
from app.persistence.models import (
    Ingredient,
    InventoryBatch,
    MealLog,
    NutritionGoal,
    Recipe,
    RecipeIngredient,
)

AS_OF = date(2026, 3, 10)
PRIMARY, SUPPORTING = IngredientRole.PRIMARY, IngredientRole.SUPPORTING


def add_ingredient(session, name, calories=100, protein=10):
    """Save an ingredient with nutrition per 100 g (carbs and fat 0).

    Args:
        session: The test database session.
        name: Ingredient name.
        calories: Calories per 100 g.
        protein: Protein per 100 g.

    Returns:
        The saved Ingredient.
    """
    ingredient = Ingredient(
        name=name,
        canonical_unit=CanonicalUnit.GRAM,
        nutrition_base_quantity=100,
        calories_per_base_unit=calories,
        protein_per_base_unit=protein,
        carbs_per_base_unit=0,
        fat_per_base_unit=0,
        nutrition_updated_at=datetime(2026, 1, 1),
    )
    session.add(ingredient)
    session.flush()
    return ingredient


def add_recipe(session, name, *lines, prep_minutes=10):
    """Save a one-serving recipe.

    Args:
        session: The test database session.
        name: Recipe name.
        *lines: ``(ingredient, quantity, role)`` tuples.
        prep_minutes: Preparation time.

    Returns:
        The saved Recipe.
    """
    recipe = Recipe(
        name=name,
        instructions=["Cook"],
        prep_minutes=prep_minutes,
        servings=1,
        recipe_ingredients=[
            RecipeIngredient(ingredient=ingredient, quantity=quantity, role=role)
            for ingredient, quantity, role in lines
        ],
    )
    session.add(recipe)
    session.flush()
    return recipe


def stock(ingredient, quantity, use_by=None, batch_id=None):
    """Build an in-memory batch copy for an ingredient.

    Args:
        ingredient: The ingredient stocked.
        quantity: Quantity remaining.
        use_by: Use-by date, or None.
        batch_id: Batch id; defaults to the ingredient's id.

    Returns:
        A SimulatedBatch.
    """
    return SimulatedBatch(
        id=batch_id or ingredient.id,
        ingredient_id=ingredient.id,
        quantity_remaining=quantity,
        use_by_date=use_by,
        purchased_at=datetime(2026, 1, 1),
    )


def plan(recipes, batches, meal_count, remaining=None, ratings=None, max_prep_minutes=None):
    """Run the planner for AS_OF.

    Args:
        recipes: Candidate recipes.
        batches: Simulated inventory.
        meal_count: Meals to plan.
        remaining: Remaining macros, or None for no goal.
        ratings: Rating summaries by recipe id.
        max_prep_minutes: Prep-time limit, or None.

    Returns:
        The MealPlan.
    """
    return plan_meals(
        recipes, batches, AS_OF, remaining, ratings or {}, meal_count, max_prep_minutes
    )


def names(meal_plan):
    """List the planned recipes' names in order.

    Args:
        meal_plan: A MealPlan.

    Returns:
        The recipe names.
    """
    return [meal.recommendation.recipe.name for meal in meal_plan.meals]


def test_each_meal_is_the_best_ranked_recipe_not_yet_planned(session):
    """Meals come out best first, and a planned recipe is not repeated."""
    chicken, rice = add_ingredient(session, "Chicken"), add_ingredient(session, "Rice")
    full = add_recipe(session, "Full", (chicken, 100, PRIMARY))
    partial = add_recipe(session, "Partial", (rice, 400, PRIMARY))

    meal_plan = plan([partial, full], [stock(chicken, 1000), stock(rice, 100)], 2)

    assert names(meal_plan) == ["Full", "Partial"]


def test_a_planned_meal_changes_what_the_next_step_sees(session):
    """Stock used by one planned meal is gone for the next, so the next pick changes."""
    chicken, rice = add_ingredient(session, "Chicken"), add_ingredient(session, "Rice")
    first = add_recipe(session, "Chicken bowl", (chicken, 100, PRIMARY))
    same_stock = add_recipe(session, "Chicken wrap", (chicken, 100, PRIMARY))
    other = add_recipe(session, "Rice bowl", (rice, 100, PRIMARY), (chicken, 100, SUPPORTING))

    meal_plan = plan([first, same_stock, other], [stock(chicken, 100), stock(rice, 100)], 2)

    # Before the first meal, "Chicken wrap" (fully stocked) would rank second; afterwards its
    # only ingredient is gone, while "Rice bowl" still has its primary ingredient.
    assert names(meal_plan) == ["Chicken bowl", "Rice bowl"]
    assert meal_plan.meals[1].consumed == {rice.id: 100, chicken.id: 0}


def test_expiry_urgency_is_recalculated_after_each_meal(session):
    """Once a planned meal uses up urgent stock, later meals no longer get urgency from it."""
    spinach, rice = add_ingredient(session, "Spinach"), add_ingredient(session, "Rice")
    uses_all = add_recipe(session, "Spinach salad", (spinach, 100, PRIMARY))
    uses_some = add_recipe(
        session, "Spinach rice", (rice, 100, PRIMARY), (spinach, 50, SUPPORTING)
    )
    batches = [stock(spinach, 100, use_by=AS_OF), stock(rice, 500)]
    [before] = recommend_recipes([uses_some], batches, AS_OF, None, {}, [], {})

    meal_plan = plan([uses_all, uses_some], batches, 2)

    assert names(meal_plan) == ["Spinach salad", "Spinach rice"]
    assert before.expiry_urgency.score > 0
    assert meal_plan.meals[1].recommendation.expiry_urgency.score == 0


def test_partially_available_recipes_use_only_what_is_on_hand(session):
    """A short recipe can be planned; it draws what exists and its macros reflect that."""
    chicken = add_ingredient(session, "Chicken", calories=200, protein=30)
    bowl = add_recipe(session, "Bowl", (chicken, 200, PRIMARY))

    meal = plan([bowl], [stock(chicken, 50)], 1).meals[0]

    assert meal.consumed == {chicken.id: 50}
    assert meal.shortfalls == {chicken.id: (200, 50)}
    assert meal.macros.calories == pytest.approx(100)


def test_macros_guide_each_step_and_are_reported(session):
    """Each meal's macros come off the remaining amounts the next step and the report use."""
    chicken = add_ingredient(session, "Chicken", calories=200, protein=30)
    rice = add_ingredient(session, "Rice", calories=100, protein=2)
    first = add_recipe(session, "Chicken", (chicken, 100, PRIMARY))
    second = add_recipe(session, "Rice", (rice, 100, PRIMARY))
    remaining = RemainingMacros(calories=1000, protein=100, carbs=200, fat=50)

    meal_plan = plan([first, second], [stock(chicken, 500), stock(rice, 500)], 2, remaining)

    after_first = meal_plan.meals[0].remaining_after
    assert after_first.calories == pytest.approx(1000 - meal_plan.meals[0].macros.calories)
    assert meal_plan.meals[1].recommendation.macro_fit == recommend_recipes(
        [meal_plan.meals[1].recommendation.recipe],
        [stock(chicken, 500), stock(rice, 500)], AS_OF, after_first, {}, [], {},
    )[0].macro_fit
    total = sum(meal.macros.calories for meal in meal_plan.meals)
    assert meal_plan.remaining_at_end.calories == pytest.approx(1000 - total)


def test_without_a_nutrition_goal_no_macros_are_reported(session):
    """With no goal in effect, remaining macros stay None throughout."""
    chicken = add_ingredient(session, "Chicken")
    bowl = add_recipe(session, "Bowl", (chicken, 100, PRIMARY))

    meal_plan = plan([bowl], [stock(chicken, 500)], 1)

    assert meal_plan.meals[0].remaining_after is None
    assert meal_plan.remaining_at_end is None


def test_recipes_over_the_prep_limit_are_never_planned(session):
    """A recipe that takes longer than max_prep_minutes is left out."""
    chicken = add_ingredient(session, "Chicken")
    quick = add_recipe(session, "Quick", (chicken, 100, PRIMARY), prep_minutes=15)
    slow = add_recipe(session, "Slow", (chicken, 50, PRIMARY), prep_minutes=45)

    meal_plan = plan([slow, quick], [stock(chicken, 1000)], 2, max_prep_minutes=30)

    assert names(meal_plan) == ["Quick"]


def test_the_plan_is_shorter_when_recipes_run_out(session):
    """Asking for more meals than there are eligible recipes plans what it can and says so."""
    chicken = add_ingredient(session, "Chicken")
    bowl = add_recipe(session, "Bowl", (chicken, 100, PRIMARY))

    meal_plan = plan([bowl], [stock(chicken, 1000)], 3)

    assert names(meal_plan) == ["Bowl"]
    assert meal_plan.meals_requested == 3


def test_score_ties_prefer_a_rated_recipe_then_the_lowest_id(session):
    """Equal scores: a recipe rated 3/5 beats an unrated one; between two unrated, lowest id."""
    ingredients = [add_ingredient(session, f"Item {n}") for n in range(3)]
    unrated_low, unrated_high, rated = (
        add_recipe(session, f"Recipe {n}", (ingredient, 100, PRIMARY))
        for n, ingredient in enumerate(ingredients)
    )
    batches = [stock(ingredient, 100) for ingredient in ingredients]
    # 3/5 scores exactly the unrated enjoyment value (0.5), so all three scores tie.
    ratings = {rated.id: RatingSummary(average=3, count=2)}

    meal_plan = plan([unrated_high, rated, unrated_low], batches, 3, ratings=ratings)

    assert names(meal_plan) == [rated.name, unrated_low.name, unrated_high.name]


def test_tie_break_order_is_score_then_rated_then_average_then_id():
    """The ordering key ranks by score, then rated, then higher average, then lower id."""

    def candidate(recipe_id, score, average=None, count=0):
        """Build the fields the key reads.

        Args:
            recipe_id: Recipe id.
            score: Combined score.
            average: Average rating, or None.
            count: Number of ratings.

        Returns:
            A stand-in recommendation.
        """
        return SimpleNamespace(
            score=score,
            recipe=SimpleNamespace(id=recipe_id),
            enjoyment=SimpleNamespace(average_rating=average, rating_count=count),
        )

    ordered = sorted(
        [
            candidate(1, 0.5),
            candidate(2, 0.5, average=4, count=1),
            candidate(3, 0.5, average=5, count=1),
            candidate(4, 0.9),
            candidate(0, 0.5),
        ],
        key=_tie_break_key,
    )

    assert [c.recipe.id for c in ordered] == [4, 3, 2, 0, 1]


@pytest.mark.parametrize("meal_count", [0, -1, True, 1.5])
def test_meal_count_must_be_a_positive_whole_number(meal_count):
    """Zero, negatives, booleans, and fractions are rejected."""
    with pytest.raises(InvalidInputError, match="meal_count"):
        plan([], [], meal_count)


def test_a_negative_prep_limit_is_rejected():
    """max_prep_minutes cannot be negative."""
    with pytest.raises(InvalidInputError, match="max_prep_minutes"):
        plan([], [], 1, max_prep_minutes=-5)


def test_planning_from_the_database_writes_nothing(session):
    """The workflow plans from stored data and leaves inventory, meals, and the session as is."""
    chicken = add_ingredient(session, "Chicken")
    add_recipe(session, "Bowl", (chicken, 100, PRIMARY))
    batch = InventoryBatch(
        ingredient=chicken, quantity_initial=150, quantity_remaining=150,
        purchased_at=datetime(2026, 1, 1),
    )
    session.add_all([batch, NutritionGoal(
        calories=2000, protein=100, carbs=200, fat=60, effective_date=date(2026, 1, 1),
    )])
    session.commit()

    meal_plan = get_meal_plan(session, AS_OF, 2)

    assert names(meal_plan) == ["Bowl"]
    assert meal_plan.meals[0].consumed == {chicken.id: 100}
    assert batch.quantity_remaining == 150
    assert not session.new and not session.dirty and not session.deleted
    assert session.scalar(select(func.count()).select_from(MealLog)) == 0
