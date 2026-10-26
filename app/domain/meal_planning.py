from collections import defaultdict
from datetime import date, datetime
from typing import NamedTuple, Sequence

from app.domain.enjoyment import RatingSummary
from app.domain.nutrition_state import RemainingMacros
from app.domain.recipe_consumption import plan_recipe_consumption
from app.domain.recipe_macros import RecipeMacros, calculate_recipe_macros
from app.domain.recommendations import Recommendation, recommend_recipes
from app.errors import InvalidInputError
from app.persistence.models import Recipe

# The deterministic baseline plans one serving per meal.
SERVINGS_PER_MEAL = 1


class SimulatedBatch(NamedTuple):
    """An in-memory copy of an inventory batch, so planning never touches database objects."""

    id: int
    ingredient_id: int
    quantity_remaining: float
    use_by_date: date | None
    purchased_at: datetime


class PlannedMeal(NamedTuple):
    """One meal of a plan: why it was chosen, what it would use, and what is left afterwards."""

    recommendation: Recommendation
    # ingredient_id -> quantity this meal would draw (only what is on hand).
    consumed: dict[int, float]
    macros: RecipeMacros
    # ingredient_id -> (quantity_needed, quantity_available) for ingredients it is short of.
    shortfalls: dict[int, tuple[float, float]]
    remaining_after: RemainingMacros | None


class MealPlan(NamedTuple):
    """Planned meals for the rest of a day; it may hold fewer meals than requested."""

    meals: list[PlannedMeal]
    meals_requested: int
    remaining_at_end: RemainingMacros | None


def plan_meals(
    recipes: Sequence[Recipe],
    batches: Sequence[SimulatedBatch],
    as_of: date,
    remaining_macros: RemainingMacros | None,
    rating_summaries: dict[int, RatingSummary],
    meal_count: int,
    max_prep_minutes: int | None = None,
) -> MealPlan:
    """Plan the next meals of a day greedily, simulating each one before choosing the next.

    Each step ranks the recipes not yet planned with ``recommend_recipes`` against the simulated
    inventory and remaining macros, takes the best (ties: rated before unrated, then the higher
    average rating, then the lower recipe id), and simulates eating one serving of it. Because the
    next step ranks against the updated simulation, availability, expiry urgency, and macro fit
    all reflect the meals already planned. Partially available recipes may be planned; they use
    only what is on hand, and their macros reflect that. Nothing is persisted or mutated.

    Args:
        recipes: Candidate recipes, with ingredients and nutrition data loaded.
        batches: In-memory copies of the inventory batches.
        as_of: The calendar day being planned.
        remaining_macros: The day's remaining macros, or None when no nutrition goal is in effect
            (macros then neither guide nor appear in the plan).
        rating_summaries: Mapping of ``recipe_id`` to its rating average and count.
        meal_count: How many meals to plan; at least 1.
        max_prep_minutes: Only plan recipes that take at most this long, or None for no limit.

    Returns:
        The plan. It holds fewer than ``meal_count`` meals when no eligible recipe is left.

    Raises:
        InvalidInputError: If ``meal_count`` is not a positive whole number, ``max_prep_minutes``
            is negative, or ``as_of`` is not a calendar date.
    """
    if isinstance(meal_count, bool) or not isinstance(meal_count, int) or meal_count < 1:
        raise InvalidInputError(f"meal_count must be a positive whole number, got {meal_count!r}")
    if max_prep_minutes is not None and max_prep_minutes < 0:
        raise InvalidInputError(f"max_prep_minutes must not be negative, got {max_prep_minutes}")

    candidates = [
        recipe for recipe in recipes
        if max_prep_minutes is None or recipe.prep_minutes <= max_prep_minutes
    ]
    simulated_batches = list(batches)
    remaining = remaining_macros
    meals = []

    for _ in range(meal_count):
        # Recent frequency is informational only and never affects ranking, so it gets no
        # history here.
        ranked = recommend_recipes(
            candidates, simulated_batches, as_of, remaining, rating_summaries, [], {}
        )
        if not ranked:
            break
        chosen = min(ranked, key=_tie_break_key)

        meal, simulated_batches = _simulate_meal(chosen, simulated_batches, remaining)
        meals.append(meal)
        remaining = meal.remaining_after
        candidates = [recipe for recipe in candidates if recipe.id != chosen.recipe.id]

    return MealPlan(meals=meals, meals_requested=meal_count, remaining_at_end=remaining)


def _tie_break_key(recommendation: Recommendation) -> tuple:
    """Order recommendations best-first: score, then rated, then average rating, then lowest id.

    Args:
        recommendation: A ranked recipe.

    Returns:
        A sort key whose smallest value is the recipe to choose.
    """
    enjoyment = recommendation.enjoyment
    return (
        -recommendation.score,
        enjoyment.rating_count == 0,
        -(enjoyment.average_rating or 0),
        recommendation.recipe.id,
    )


def _simulate_meal(
    recommendation: Recommendation,
    batches: Sequence[SimulatedBatch],
    remaining: RemainingMacros | None,
) -> tuple[PlannedMeal, list[SimulatedBatch]]:
    """Work out what eating one serving of a recommended recipe would use and leave.

    Draws follow FEFO, exactly as confirming the meal would.

    Args:
        recommendation: The chosen recipe and the scores that chose it.
        batches: The simulated inventory before this meal.
        remaining: The remaining macros before this meal, or None without a goal.

    Returns:
        The planned meal, and new batch copies with its draws taken out (emptied ones dropped).
    """
    batches_by_ingredient = defaultdict(list)
    for batch in batches:
        batches_by_ingredient[batch.ingredient_id].append(batch)
    recipe = recommendation.recipe
    consumption = plan_recipe_consumption(recipe, SERVINGS_PER_MEAL, batches_by_ingredient)
    macros = calculate_recipe_macros(recipe, quantity_overrides=consumption.fulfilled_quantities)

    remaining_after = None
    if remaining is not None:
        remaining_after = RemainingMacros(
            calories=remaining.calories - macros.calories,
            protein=remaining.protein - macros.protein,
            carbs=remaining.carbs - macros.carbs,
            fat=remaining.fat - macros.fat,
        )
    consumed = defaultdict(float)
    taken = defaultdict(float)
    for line in consumption.lines:
        consumed[line.recipe_ingredient.ingredient_id] += line.quantity_fulfilled
        for draw in line.draws:
            taken[draw.batch.id] += draw.quantity
    after = [
        batch._replace(quantity_remaining=batch.quantity_remaining - taken[batch.id])
        for batch in batches
    ]
    meal = PlannedMeal(
        recommendation=recommendation,
        consumed=dict(consumed),
        macros=macros,
        shortfalls=consumption.shortfalls,
        remaining_after=remaining_after,
    )
    return meal, [batch for batch in after if batch.quantity_remaining > 0]

