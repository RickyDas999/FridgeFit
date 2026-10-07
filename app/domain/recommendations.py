from collections import defaultdict
from datetime import date
from typing import NamedTuple, Sequence

from app.domain.availability import RecipeAvailability, assess_recipe_availability
from app.domain.enjoyment import (
    RecipeEnjoyment,
    assess_recipe_enjoyment,
    group_ratings_by_recipe,
)
from app.domain.freshness import RecipeFreshness, assess_recipe_freshness
from app.domain.inventory_aggregation import aggregate_inventory_by_ingredient
from app.domain.macro_fit import MacroFit, assess_macro_fit
from app.domain.nutrition_state import RemainingMacros
from app.domain.recent_frequency import (
    RecentFrequency,
    assess_recent_frequency,
    group_meal_dates_by_recipe,
)
from app.domain.validation import validate_calendar_date
from app.persistence.models import InventoryBatch, MealFeedback, MealLog, Recipe

DEFAULT_WEIGHTS = {
    "availability": 0.4,
    "freshness": 0.3,
    "macro_fit": 0.2,
    "enjoyment": 0.1,
}


class Recommendation(NamedTuple):
    """A ranked recipe with its combined score and the details behind it."""

    recipe: Recipe
    score: float
    availability: RecipeAvailability
    freshness: RecipeFreshness
    macro_fit: MacroFit | None
    enjoyment: RecipeEnjoyment
    recent_frequency: RecentFrequency


def combine_scores(scores: dict[str, float]) -> float:
    """Combine component scores into one 0-1 score using the default weights.

    Only the components present in ``scores`` are weighted; their weights are rescaled to sum
    to 1, so the result stays on a 0-1 scale while some components are not yet implemented.

    Args:
        scores: Mapping of component name (a key of ``DEFAULT_WEIGHTS``) to a 0-1 score.

    Returns:
        The weighted combined score.
    """
    total_weight = sum(DEFAULT_WEIGHTS[name] for name in scores)
    return sum(DEFAULT_WEIGHTS[name] * score for name, score in scores.items()) / total_weight


def recommend_recipes(
    recipes: Sequence[Recipe],
    batches: Sequence[InventoryBatch],
    as_of: date,
    remaining_macros: RemainingMacros | None,
    meal_feedback: Sequence[MealFeedback],
    meal_logs: Sequence[MealLog],
) -> list[Recommendation]:
    """Rank recipes by how well they can be made on a given date.

    Recipes that are ineligible (more than one PRIMARY ingredient missing) are excluded.

    Args:
        recipes: Candidate recipes. Their ingredients and nutrition data must be loadable.
        batches: Current inventory batches across all ingredients.
        as_of: The calendar date to recommend for, used to judge freshness.
        remaining_macros: Today's remaining macros, as returned by
            ``calculate_remaining_macros``. Pass None when no nutrition goal is in effect yet;
            macro fit is then left out of the ranking.
        meal_feedback: The user's meal ratings. Each one's ``meal_log`` must be loadable. Pass
            an empty sequence when nothing has been rated yet.
        meal_logs: The user's meal history, used only to report recent frequency; it never
            affects the ranking.

    Returns:
        Eligible recipes as Recommendations, highest score first.

    Raises:
        InvalidInputError: If ``as_of`` is not a calendar date, a recipe is invalid, or a rating
            is outside 1-5.
    """
    validate_calendar_date(as_of)
    ratings_by_recipe = group_ratings_by_recipe(meal_feedback)
    meal_dates_by_recipe = group_meal_dates_by_recipe(meal_logs, as_of)

    inventory_totals = aggregate_inventory_by_ingredient(batches)
    batches_by_ingredient = defaultdict(list)
    for batch in batches:
        batches_by_ingredient[batch.ingredient_id].append(batch)

    recommendations = []
    for recipe in recipes:
        availability = assess_recipe_availability(recipe, inventory_totals)
        if not availability.is_eligible:
            continue
        freshness = assess_recipe_freshness(recipe, batches_by_ingredient, as_of)
        scores = {"availability": availability.score, "freshness": freshness.score}

        macro_fit = None
        if remaining_macros is not None:
            macro_fit = assess_macro_fit(recipe, remaining_macros)
            scores["macro_fit"] = macro_fit.score

        enjoyment = assess_recipe_enjoyment(recipe, ratings_by_recipe)
        scores["enjoyment"] = enjoyment.score

        recommendations.append(
            Recommendation(
                recipe=recipe,
                score=combine_scores(scores),
                availability=availability,
                freshness=freshness,
                macro_fit=macro_fit,
                enjoyment=enjoyment,
                recent_frequency=assess_recent_frequency(recipe, meal_dates_by_recipe, as_of),
            )
        )

    return sorted(recommendations, key=lambda r: r.score, reverse=True)
