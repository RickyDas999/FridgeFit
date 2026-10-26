from collections import defaultdict
from datetime import date, datetime
from typing import NamedTuple, Sequence

from app.domain.enjoyment import RatingSummary
from app.domain.nutrition_state import RemainingMacros
from app.domain.recipe_consumption import plan_recipe_consumption
from app.domain.recipe_macros import RecipeMacros, calculate_recipe_macros
from app.domain.recommendations import Recommendation, recommend_recipes
from app.domain.validation import validate_servings
from app.errors import InvalidInputError
from app.persistence.models import Recipe


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
    # batch id -> quantity drawn from that batch (FEFO), e.g. to see which expiring stock is used.
    batch_draws: dict[int, float]
    macros: RecipeMacros
    # ingredient_id -> (quantity_needed, quantity_available) for ingredients it is short of.
    shortfalls: dict[int, tuple[float, float]]
    remaining_after: RemainingMacros | None


class MealSimulation(NamedTuple):
    """What eating some servings of one recipe would use, supply, and leave behind."""

    # ingredient_id -> quantity drawn (only what is on hand).
    consumed: dict[int, float]
    # batch id -> quantity drawn from that batch (FEFO).
    batch_draws: dict[int, float]
    macros: RecipeMacros
    # ingredient_id -> (quantity_needed, quantity_available) for ingredients it is short of.
    shortfalls: dict[int, tuple[float, float]]
    remaining_after: RemainingMacros | None
    # The inventory afterwards: new copies with the draws taken out, emptied batches dropped.
    batches_after: list[SimulatedBatch]


class MealPlan(NamedTuple):
    """Planned meals for the rest of a day; it may hold fewer meals than requested."""

    meals: list[PlannedMeal]
    meals_requested: int
    # Every meal in the plan is this many servings.
    servings_per_meal: float
    remaining_at_end: RemainingMacros | None


def plan_meals(
    recipes: Sequence[Recipe],
    batches: Sequence[SimulatedBatch],
    as_of: date,
    remaining_macros: RemainingMacros | None,
    rating_summaries: dict[int, RatingSummary],
    meal_count: int,
    max_prep_minutes: int | None = None,
    servings_per_meal: float = 1,
) -> MealPlan:
    """Plan the next meals of a day greedily, simulating each one before choosing the next.

    Each step ranks the recipes not yet planned with ``recommend_recipes`` against the simulated
    inventory and remaining macros, takes the best (ties: rated before unrated, then the higher
    average rating, then the lower recipe id), and simulates eating ``servings_per_meal`` servings
    of it. Because the next step ranks against the updated simulation, availability, expiry
    urgency, and macro fit all reflect the meals already planned. Partially available recipes may
    be planned; they use only what is on hand, and their macros reflect that. Nothing is
    persisted or mutated.

    Ranking scores one serving, as recommendations always do; only the simulation uses
    ``servings_per_meal``. So with more than one serving, a recipe can be chosen that is short of
    stock or over budget at the real portion: the plan reports that, but does not avoid it.

    Args:
        recipes: Candidate recipes, with ingredients and nutrition data loaded.
        batches: In-memory copies of the inventory batches.
        as_of: The calendar day being planned.
        remaining_macros: The day's remaining macros, or None when no nutrition goal is in effect
            (macros then neither guide nor appear in the plan).
        rating_summaries: Mapping of ``recipe_id`` to its rating average and count.
        meal_count: How many meals to plan; at least 1.
        max_prep_minutes: Only plan recipes that take at most this long, or None for no limit.
        servings_per_meal: Servings in every planned meal; any positive number, as in meal
            confirmation.

    Returns:
        The plan. It holds fewer than ``meal_count`` meals when no eligible recipe is left.

    Raises:
        InvalidInputError: If ``meal_count`` is not a positive whole number, ``max_prep_minutes``
            is negative, ``servings_per_meal`` is not positive, or ``as_of`` is not a calendar
            date.
    """
    if isinstance(meal_count, bool) or not isinstance(meal_count, int) or meal_count < 1:
        raise InvalidInputError(f"meal_count must be a positive whole number, got {meal_count!r}")
    if max_prep_minutes is not None and max_prep_minutes < 0:
        raise InvalidInputError(f"max_prep_minutes must not be negative, got {max_prep_minutes}")
    validate_servings(servings_per_meal)

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

        simulation = simulate_meal(
            chosen.recipe, simulated_batches, remaining, servings_per_meal
        )
        meals.append(PlannedMeal(
            recommendation=chosen,
            consumed=simulation.consumed,
            batch_draws=simulation.batch_draws,
            macros=simulation.macros,
            shortfalls=simulation.shortfalls,
            remaining_after=simulation.remaining_after,
        ))
        simulated_batches = simulation.batches_after
        remaining = simulation.remaining_after
        candidates = [recipe for recipe in candidates if recipe.id != chosen.recipe.id]

    return MealPlan(
        meals=meals,
        meals_requested=meal_count,
        servings_per_meal=servings_per_meal,
        remaining_at_end=remaining,
    )


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


def simulate_meal(
    recipe: Recipe,
    batches: Sequence[SimulatedBatch],
    remaining: RemainingMacros | None,
    servings: float,
) -> MealSimulation:
    """Work out what eating some servings of a recipe would use, supply, and leave.

    Draws follow FEFO, exactly as confirming the meal would; a short ingredient uses only what is
    on hand. Pure: the given batches are not changed.

    Args:
        recipe: The recipe eaten, with ingredients and nutrition data loaded.
        batches: The simulated inventory before this meal.
        remaining: The remaining macros before this meal, or None without a goal.
        servings: Servings eaten; any positive number.

    Returns:
        The simulation, including the inventory afterwards.

    Raises:
        InvalidInputError: If the recipe is invalid or ``servings`` is not positive.
    """
    batches_by_ingredient = defaultdict(list)
    for batch in batches:
        batches_by_ingredient[batch.ingredient_id].append(batch)
    consumption = plan_recipe_consumption(recipe, servings, batches_by_ingredient)
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
    # .get, not taken[...]: indexing a defaultdict inserts a 0.0 entry for every batch, which
    # would then show up in batch_draws as a draw from stock the meal never touched.
    after = [
        batch._replace(quantity_remaining=batch.quantity_remaining - taken.get(batch.id, 0.0))
        for batch in batches
    ]
    return MealSimulation(
        consumed=dict(consumed),
        batch_draws=dict(taken),
        macros=macros,
        shortfalls=consumption.shortfalls,
        remaining_after=remaining_after,
        batches_after=[batch for batch in after if batch.quantity_remaining > 0],
    )



def plan_violations(
    recipes: Sequence[Recipe],
    known_recipe_ids: set[int],
    meal_count: int,
    max_prep_minutes: int | None,
) -> list[str]:
    """List every hard planning constraint a sequence of meals breaks; empty means it complies.

    The constraints: no more meals than requested, only known recipes, no recipe twice, and none
    over the prep-time limit. Whoever proposed the sequence, the rules are the same.

    Args:
        recipes: The planned recipes, in order.
        known_recipe_ids: Ids of the kitchen's recipes.
        meal_count: How many meals were requested.
        max_prep_minutes: The prep-time limit, or None for no limit.

    Returns:
        One readable message per violation, in plan order.
    """
    violations = []
    if len(recipes) > meal_count:
        violations.append(f"{len(recipes)} meals planned, {meal_count} requested")
    seen = set()
    for recipe in recipes:
        if recipe.id not in known_recipe_ids:
            violations.append(f"{recipe.name!r} is not one of the kitchen's recipes")
        if recipe.id in seen:
            violations.append(f"{recipe.name!r} is planned more than once")
        seen.add(recipe.id)
        if max_prep_minutes is not None and recipe.prep_minutes > max_prep_minutes:
            violations.append(
                f"{recipe.name!r} takes {recipe.prep_minutes} min, "
                f"over the {max_prep_minutes}-min limit"
            )
    return violations
