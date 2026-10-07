from typing import NamedTuple

from app.domain.nutrition_state import RemainingMacros
from app.domain.recipe_macros import RecipeMacros, calculate_recipe_macros
from app.persistence.models import Recipe

MACRO_WEIGHTS = {"calories": 0.4, "protein": 0.3, "fat": 0.2, "carbs": 0.1}
PROTEIN_ACCEPTABLE_EXCESS = 1.5
PROTEIN_ZERO_SCORE_EXCESS = 3.0
ADEQUATE_CARB_SHARE = 0.25
ZERO_CARB_SCORE = 0.5


class MacroFit(NamedTuple):
    """How well one serving of a recipe fits today's remaining macros."""

    score: float
    per_serving: RecipeMacros


def _stay_under_score(serving: float, remaining: float) -> float:
    """Score a macro that should stay within what is left of today's target.

    Args:
        serving: Amount in one serving.
        remaining: Amount left of today's target; may be zero or negative.

    Returns:
        1.0 if the serving fits, otherwise the share of the serving that fits.
    """
    if serving <= max(remaining, 0.0):
        return 1.0
    return max(remaining, 0.0) / serving


def _protein_score(serving: float, remaining: float) -> float:
    """Score protein, rewarding servings that cover the remaining target.

    Coverage up to the remaining target scores proportionally. Moderate excess, up to
    ``PROTEIN_ACCEPTABLE_EXCESS`` times the target, is not penalized; beyond that the score falls
    linearly to 0 at ``PROTEIN_ZERO_SCORE_EXCESS`` times the target.

    Args:
        serving: Protein in one serving.
        remaining: Protein left of today's target; may be zero or negative.

    Returns:
        The 0-1 protein score; 1.0 if today's target is already met.
    """
    if remaining <= 0:
        return 1.0
    coverage = serving / remaining
    if coverage <= PROTEIN_ACCEPTABLE_EXCESS:
        return min(coverage, 1.0)
    span = PROTEIN_ZERO_SCORE_EXCESS - PROTEIN_ACCEPTABLE_EXCESS
    return max(0.0, (PROTEIN_ZERO_SCORE_EXCESS - coverage) / span)


def _carbs_score(serving: float, remaining: float) -> float:
    """Score carbohydrates: stay within the target while encouraging an adequate amount.

    Within budget, a serving providing at least ``ADEQUATE_CARB_SHARE`` of the remaining carbs
    scores 1.0; below that the score falls linearly to ``ZERO_CARB_SCORE`` at zero carbs. Over
    budget, or once the target is used up, carbs score like any stay-under macro.

    Args:
        serving: Carbohydrates in one serving.
        remaining: Carbohydrates left of today's target; may be zero or negative.

    Returns:
        The 0-1 carbohydrate score.
    """
    if remaining <= 0 or serving > remaining:
        return _stay_under_score(serving, remaining)
    share = serving / remaining
    if share >= ADEQUATE_CARB_SHARE:
        return 1.0
    return ZERO_CARB_SCORE + (1.0 - ZERO_CARB_SCORE) * share / ADEQUATE_CARB_SHARE


def assess_macro_fit(recipe: Recipe, remaining: RemainingMacros) -> MacroFit:
    """Score how well one serving of a recipe fits today's remaining macros.

    Each macro is scored on its own rule, then combined using ``MACRO_WEIGHTS``, which follow
    the macro priorities: calories, protein, fat, carbohydrates.

    Args:
        recipe: The recipe to assess. Its ingredients and their nutrition data must be loadable.
        remaining: Today's remaining macros, as returned by ``calculate_remaining_macros``.

    Returns:
        The 0-1 macro-fit score and one serving's macros.

    Raises:
        InvalidInputError: If the recipe is invalid, including a non-positive serving count.
    """
    total = calculate_recipe_macros(recipe)
    per_serving = RecipeMacros(*(value / recipe.servings for value in total))

    scores = {
        "calories": _stay_under_score(per_serving.calories, remaining.calories),
        "protein": _protein_score(per_serving.protein, remaining.protein),
        "fat": _stay_under_score(per_serving.fat, remaining.fat),
        "carbs": _carbs_score(per_serving.carbs, remaining.carbs),
    }
    score = sum(MACRO_WEIGHTS[name] * value for name, value in scores.items())
    return MacroFit(score=score, per_serving=per_serving)
