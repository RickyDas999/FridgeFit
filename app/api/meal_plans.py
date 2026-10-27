import logging
from datetime import date
from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from app.api.recipes import MacrosResponse
from app.api.session import SessionDep
from app.application.ai_planner import PlanningResult, baseline_result, plan_day
from app.application.planning_tools import PlanningRequest, load_planning_snapshot
from app.domain.meal_planning import PlannedMeal
from app.domain.nutrition_state import RemainingMacros
from app.domain.recipe_macros import RecipeMacros
from app.evaluation.pricing import estimate_cost

router = APIRouter(prefix="/meal-plans", tags=["meal-plans"])
logger = logging.getLogger(__name__)

FallbackReason = Literal["ai_disabled", "ai_failed", "ai_plan_invalid", "ai_limit"]


class MealPlanCreate(BaseModel):
    """What to plan: how many more meals today, and the limits and preference for them."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, str_strip_whitespace=True)

    meal_count: int = Field(ge=1, le=5)
    max_prep_minutes: int | None = Field(default=None, ge=1, le=240)
    servings_per_meal: float = Field(default=1, gt=0)
    preference: str | None = Field(
        default=None, max_length=300, description="Free text for the AI planner, e.g. 'light'."
    )
    as_of: date | None = Field(default=None, description="Defaults to today on the server.")
    planner: Literal["ai", "baseline"] = Field(
        default="ai",
        description="'baseline' asks for FridgeFit's deterministic plan and never calls Claude.",
    )


class IngredientAmountResponse(BaseModel):
    """A quantity of one ingredient, in its canonical unit."""

    ingredient_id: int
    name: str
    unit: str
    quantity: float


class ShortageResponse(BaseModel):
    """An ingredient a meal needs more of than is on hand at that point in the plan."""

    ingredient_id: int
    name: str
    unit: str
    needed: float
    available: float


class PlannedMealResponse(BaseModel):
    """One meal of the plan, as FridgeFit simulated it."""

    recipe_id: int
    name: str
    prep_minutes: int
    servings: float
    ingredients_used: list[IngredientAmountResponse]
    shortages: list[ShortageResponse]
    macros: MacrosResponse
    remaining_after: MacrosResponse | None


class MealPlanResponse(BaseModel):
    """The plan, where it came from, and why the AI plan was not used when it was not."""

    source: Literal["ai", "baseline"]
    explanation: str | None = Field(description="The AI's own words; null for the baseline.")
    fallback_reason: FallbackReason | None
    meals: list[PlannedMealResponse]
    remaining_at_end: MacrosResponse | None


def fallback_code(result: PlanningResult) -> FallbackReason | None:
    """Reduce why the AI plan was not used to a coarse, public code.

    The code comes from the attempt's recorded outcome, never from parsing the reason text, so
    provider error messages stay out of the response.

    Args:
        result: The planning result.

    Returns:
        None when the AI plan is used, otherwise the code.
    """
    if result.source == "ai":
        return None
    if result.attempt is None:
        return "ai_disabled"
    # "submitted" here means the loop accepted the plan but the final replay rejected it.
    if result.attempt.outcome in ("invalid_plan", "submitted"):
        return "ai_plan_invalid"
    return "ai_failed"


def macros_response(macros: RecipeMacros | RemainingMacros | None) -> MacrosResponse | None:
    """Convert macros (a meal's, or what is left of the day) into their response body.

    Args:
        macros: The macros, or None when there is no nutrition goal.

    Returns:
        The response body, or None.
    """
    return None if macros is None else MacrosResponse(**macros._asdict())


def planned_meal_response(meal: PlannedMeal, servings: float) -> PlannedMealResponse:
    """Convert one planned meal into its response body.

    Args:
        meal: The planned meal.
        servings: Servings per meal in this plan.

    Returns:
        The response body.
    """
    recipe = meal.recommendation.recipe
    ingredients = {line.ingredient_id: line.ingredient for line in recipe.recipe_ingredients}
    return PlannedMealResponse(
        recipe_id=recipe.id,
        name=recipe.name,
        prep_minutes=recipe.prep_minutes,
        servings=servings,
        ingredients_used=[
            IngredientAmountResponse(
                ingredient_id=i, name=ingredients[i].name,
                unit=ingredients[i].canonical_unit.value, quantity=quantity,
            )
            for i, quantity in meal.consumed.items() if quantity > 0
        ],
        shortages=[
            ShortageResponse(
                ingredient_id=i, name=ingredients[i].name,
                unit=ingredients[i].canonical_unit.value, needed=needed, available=available,
            )
            for i, (needed, available) in meal.shortfalls.items()
        ],
        macros=macros_response(meal.macros),
        remaining_after=macros_response(meal.remaining_after),
    )


def log_attempt(result: PlanningResult, code: FallbackReason | None) -> None:
    """Record how the AI attempt went in the server log; none of this is in the response.

    Args:
        result: The planning result.
        code: The public fallback code.
    """
    attempt = result.attempt
    if attempt is None:
        logger.info("meal plan: source=%s fallback=%s (%s)", result.source, code,
                    result.fallback_reason)
        return
    usage = attempt.usage
    cost = estimate_cost(usage)
    logger.info(
        "meal plan: source=%s fallback=%s outcome=%s detail=%s model=%s effort=%s "
        "input_tokens=%d output_tokens=%d model_calls=%d tool_calls=%d rejected_plans=%d "
        "seconds=%.1f est_cost_usd=%s",
        result.source, code, attempt.outcome, attempt.detail, usage.model, usage.effort,
        usage.input_tokens, usage.output_tokens, usage.model_calls, usage.tool_calls,
        usage.rejected_plans, usage.total_seconds,
        "unknown" if cost is None else f"{cost:.5f}",
    )


@router.post("")
def create_meal_plan(
    body: MealPlanCreate, request: Request, session: SessionDep
) -> MealPlanResponse:
    """Plan the rest of a day's meals with the AI planner, or the deterministic baseline.

    Nothing is written: the plan is a proposal. The AI plan is returned only when FridgeFit's
    own checks pass; otherwise the baseline plan comes back with a coarse ``fallback_reason``.
    AI or provider failures never turn into an error response. ``planner="baseline"`` returns
    the baseline plan directly, whatever the AI configuration, without a ``fallback_reason``.

    Args:
        body: The planning request.
        request: The incoming request, used to reach the app's planner configuration.
        session: The request's database session.

    Returns:
        The plan.

    Raises:
        InvalidInputError: If the request's numbers are invalid for the planner.
    """
    snapshot = load_planning_snapshot(session, PlanningRequest(
        as_of=body.as_of or date.today(),
        meal_count=body.meal_count,
        max_prep_minutes=body.max_prep_minutes,
        servings_per_meal=body.servings_per_meal,
        preference=body.preference or None,
    ))
    state = request.app.state
    config, client = state.planner_config, state.planner_client
    if body.planner == "baseline":
        # Asked for, not a fallback: free, no Claude call, and nothing counted against the cap.
        result = baseline_result(snapshot, "baseline requested", None)
        code = None
    # Only attempts that would call Claude count. The day is the server's, not the request's
    # as_of, so changing as_of cannot get around the cap.
    elif config is not None and client is not None and not state.planner_limit.try_take(
        date.today()
    ):
        limit = state.planner_limit.limit
        result = baseline_result(snapshot, f"daily limit of {limit} AI plans reached", None)
        code = "ai_limit"
    else:
        result = plan_day(snapshot, config, client)
        code = fallback_code(result)
    log_attempt(result, code)
    plan = result.plan
    return MealPlanResponse(
        source=result.source,
        explanation=result.explanation,
        fallback_reason=code,
        meals=[planned_meal_response(m, plan.servings_per_meal) for m in plan.meals],
        remaining_at_end=macros_response(plan.remaining_at_end),
    )
