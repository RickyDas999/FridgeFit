"""The read-only tools an AI planner uses to inspect FridgeFit (Milestone 7 Slice 3).

Each tool reads one in-memory snapshot, loaded once per planning request, and calls the same
domain functions the deterministic planner uses. Nothing here writes product state, and no tool
is an HTTP endpoint: the planning loop calls ``run_tool`` in-process.

Tool inputs are Pydantic models that reject anything unexpected (this is the boundary where
model-written input arrives); each tool's JSON input schema is generated from the same model.
Outputs are Pydantic models serialized to JSON, with numbers rounded for display only.
"""

import json
from collections import defaultdict
from datetime import date, timedelta
from typing import Callable, NamedTuple

from pydantic import BaseModel, ConfigDict, Field, StrictInt, ValidationError
from sqlalchemy.orm import Session

from app.application.meal_planning import to_simulated_batches
from app.application.recommendations import load_recommendation_inputs
from app.domain.availability import assess_recipe_availability
from app.domain.enjoyment import RatingSummary
from app.domain.expiry_urgency import EXPIRING_SOON_DAYS
from app.domain.inventory_aggregation import aggregate_inventory_by_ingredient
from app.domain.meal_planning import (
    ReplayedPlan,
    SimulatedBatch,
    plan_violations,
    ranking_key,
    replay_plan,
    simulate_meal,
    validate_plan_request,
)
from app.domain.nutrition_state import RemainingMacros
from app.domain.recipe_macros import RecipeMacros, calculate_recipe_macros
from app.domain.recommendations import recommend_recipes
from app.persistence.enums import IngredientRole
from app.persistence.models import Recipe

# At most this many ranked candidates go to the model, however many recipes exist.
MAX_CANDIDATES = 10


class PlanningRequest(NamedTuple):
    """What the user asked to plan."""

    as_of: date
    meal_count: int
    max_prep_minutes: int | None
    servings_per_meal: float
    preference: str | None


class PlanningSnapshot(NamedTuple):
    """Everything the tools read for one planning request, loaded once."""

    request: PlanningRequest
    recipes_by_id: dict[int, Recipe]
    batches: list[SimulatedBatch]
    remaining: RemainingMacros | None
    rating_summaries: dict[int, RatingSummary]


class ToolResult(NamedTuple):
    """A tool's answer as the model receives it: JSON text, and whether it is an error."""

    content: str
    is_error: bool


def load_planning_snapshot(session: Session, request: PlanningRequest) -> PlanningSnapshot:
    """Load the data every planning tool reads, once, as plain in-memory values.

    Args:
        session: An open database session; nothing is written.
        request: The planning request.

    Returns:
        The snapshot.

    Raises:
        InvalidInputError: If the request's numbers or date are invalid.
    """
    validate_plan_request(request.meal_count, request.max_prep_minutes, request.servings_per_meal)
    inputs = load_recommendation_inputs(session, request.as_of)
    return PlanningSnapshot(
        request=request,
        recipes_by_id={recipe.id: recipe for recipe in inputs.recipes},
        batches=to_simulated_batches(inputs.batches),
        remaining=inputs.remaining,
        rating_summaries=inputs.rating_summaries,
    )


# --- Input models: what the model may send. Unknown fields and wrong types are rejected. ------


class ToolModel(BaseModel):
    """Base for tool inputs and outputs: no unknown fields, finite numbers only."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class GetPlanningContextInput(ToolModel):
    """No input: the context describes the current planning request."""


class GetRecipeInput(ToolModel):
    """Input for get_recipe."""

    recipe_id: StrictInt = Field(description="Id of a recipe from the planning context.")


class SimulatePlanInput(ToolModel):
    """Input for simulate_plan."""

    recipe_ids: list[StrictInt] = Field(
        min_length=1,
        description="Recipe ids in the order they would be eaten, one per meal.",
    )


# --- Output models: what the model reads back. ----------------------------------------------


class Macros(ToolModel):
    """Calories (kcal) and protein, carbs, and fat (g), rounded."""

    calories: float
    protein: float
    carbs: float
    fat: float


class StockItem(ToolModel):
    """One ingredient's stock, across its batches."""

    ingredient_id: int
    ingredient: str
    unit: str
    on_hand: float
    earliest_use_by: date | None
    due_soon: float = Field(description=f"Quantity due within {EXPIRING_SOON_DAYS} days.")


class Candidate(ToolModel):
    """One ranked recipe, with the scores the deterministic ranking gives it (0-1)."""

    recipe_id: int
    name: str
    prep_minutes: int
    score: float
    availability: float
    expiry_urgency: float
    macro_fit: float | None
    average_rating: float | None
    missing_ingredients: list[str]
    per_serving: Macros


class PlanningContext(ToolModel):
    """The request, what is left of today's goal, the stock, and the best-ranked candidates."""

    date: date
    meal_count: int
    max_prep_minutes: int | None
    servings_per_meal: float
    preference: str | None
    remaining_macros: Macros | None
    stock: list[StockItem]
    candidates: list[Candidate]
    eligible_recipes: int = Field(description="Eligible recipes in total, before the cap.")


class RecipeLine(ToolModel):
    """One ingredient of a recipe, per serving, against what is on hand."""

    ingredient: str
    unit: str
    role: str
    per_serving: float
    on_hand: float


class RecipeDetails(ToolModel):
    """One recipe in full."""

    recipe_id: int
    name: str
    prep_minutes: int
    within_prep_limit: bool
    eligible: bool
    ingredients: list[RecipeLine]
    per_serving: Macros


class Amount(ToolModel):
    """A quantity of one ingredient."""

    ingredient: str
    unit: str
    quantity: float


class Shortage(ToolModel):
    """An ingredient a meal needs more of than is on hand at that point."""

    ingredient: str
    unit: str
    needed: float
    available: float


class SimulatedMeal(ToolModel):
    """What one meal of the proposed sequence would use and supply."""

    recipe_id: int
    name: str
    consumed: list[Amount]
    shortages: list[Shortage]
    macros: Macros
    remaining_after: Macros | None
    warning: str | None


class Simulation(ToolModel):
    """The proposed sequence, simulated meal by meal, and the hard constraints it breaks."""

    meals: list[SimulatedMeal]
    remaining_at_end: Macros | None
    violations: list[str]
    within_constraints: bool


class ToolError(ToolModel):
    """Why a tool call could not be answered; nothing was done."""

    error: str


# --- Tools. -------------------------------------------------------------------------------


def get_planning_context(snapshot: PlanningSnapshot, _: GetPlanningContextInput) -> ToolModel:
    """Describe the request, today's remaining macros, the stock, and the top-ranked recipes.

    Args:
        snapshot: The planning request's data.
        _: No input.

    Returns:
        The PlanningContext.
    """
    request = snapshot.request
    allowed = _within_prep_limit(snapshot)
    ranked = sorted(
        recommend_recipes(
            allowed, snapshot.batches, request.as_of, snapshot.remaining,
            snapshot.rating_summaries, [], {},
        ),
        key=ranking_key,
    )
    return PlanningContext(
        date=request.as_of,
        meal_count=request.meal_count,
        max_prep_minutes=request.max_prep_minutes,
        servings_per_meal=request.servings_per_meal,
        preference=request.preference,
        remaining_macros=_macros(snapshot.remaining),
        stock=_stock(snapshot),
        candidates=[
            Candidate(
                recipe_id=r.recipe.id,
                name=r.recipe.name,
                prep_minutes=r.recipe.prep_minutes,
                score=round(r.score, 2),
                availability=round(r.availability.score, 2),
                expiry_urgency=round(r.expiry_urgency.score, 2),
                macro_fit=None if r.macro_fit is None else round(r.macro_fit.score, 2),
                average_rating=r.enjoyment.average_rating,
                missing_ingredients=[
                    line.recipe_ingredient.ingredient.name
                    for line in r.availability.ingredients if line.is_missing
                ],
                per_serving=_macros(_per_serving_macros(r.recipe)),
            )
            for r in ranked[:MAX_CANDIDATES]
        ],
        eligible_recipes=len(ranked),
    )


def get_recipe(snapshot: PlanningSnapshot, tool_input: GetRecipeInput) -> ToolModel:
    """Describe one recipe: ingredients per serving against stock, prep time, and macros.

    Args:
        snapshot: The planning request's data.
        tool_input: Which recipe.

    Returns:
        The RecipeDetails, or a ToolError for an unknown recipe id.
    """
    recipe = snapshot.recipes_by_id.get(tool_input.recipe_id)
    if recipe is None:
        return _unknown_recipes([tool_input.recipe_id])
    totals = aggregate_inventory_by_ingredient(snapshot.batches)
    availability = assess_recipe_availability(recipe, totals)
    limit = snapshot.request.max_prep_minutes
    return RecipeDetails(
        recipe_id=recipe.id,
        name=recipe.name,
        prep_minutes=recipe.prep_minutes,
        within_prep_limit=limit is None or recipe.prep_minutes <= limit,
        eligible=availability.is_eligible,
        ingredients=[
            RecipeLine(
                ingredient=line.recipe_ingredient.ingredient.name,
                unit=line.recipe_ingredient.ingredient.canonical_unit.value,
                role=line.recipe_ingredient.role.value,
                per_serving=round(line.quantity_per_serving, 1),
                on_hand=round(line.quantity_on_hand, 1),
            )
            for line in availability.ingredients
        ],
        per_serving=_macros(_per_serving_macros(recipe)),
    )


def simulate_plan(snapshot: PlanningSnapshot, tool_input: SimulatePlanInput) -> ToolModel:
    """Simulate eating the given recipes in order and report what each meal uses and leaves.

    The simulation is the one the deterministic planner uses, at the request's servings per
    meal; a recipe the recommender would exclude is simulated but carries a warning.

    Args:
        snapshot: The planning request's data.
        tool_input: The proposed recipe ids, in eating order.

    Returns:
        The Simulation, or a ToolError if any recipe id is unknown.
    """
    unknown = [i for i in tool_input.recipe_ids if i not in snapshot.recipes_by_id]
    if unknown:
        return _unknown_recipes(unknown)
    request = snapshot.request
    recipes = [snapshot.recipes_by_id[i] for i in tool_input.recipe_ids]
    names = _ingredient_names(snapshot)
    units = _ingredient_units(snapshot)
    batches = snapshot.batches
    remaining = snapshot.remaining
    meals = []
    for recipe in recipes:
        warning = _ineligibility(recipe, batches)
        simulation = simulate_meal(recipe, batches, remaining, request.servings_per_meal)
        meals.append(SimulatedMeal(
            recipe_id=recipe.id,
            name=recipe.name,
            consumed=[
                Amount(ingredient=names[i], unit=units[i], quantity=round(quantity, 1))
                for i, quantity in simulation.consumed.items() if quantity > 0
            ],
            shortages=[
                Shortage(
                    ingredient=names[i], unit=units[i],
                    needed=round(needed, 1), available=round(available, 1),
                )
                for i, (needed, available) in simulation.shortfalls.items()
            ],
            macros=_macros(simulation.macros),
            remaining_after=_macros(simulation.remaining_after),
            warning=warning,
        ))
        batches = simulation.batches_after
        remaining = simulation.remaining_after
    violations = plan_violations(
        recipes, set(snapshot.recipes_by_id), request.meal_count, request.max_prep_minutes
    )
    return Simulation(
        meals=meals,
        remaining_at_end=_macros(remaining),
        violations=violations,
        within_constraints=not violations,
    )


def proposal_problems(snapshot: PlanningSnapshot, recipe_ids: list[int]) -> list[str]:
    """Check a proposed plan deterministically: every reason it is not a valid plan.

    Args:
        snapshot: The planning request's data.
        recipe_ids: The proposed recipe ids, in eating order.

    Returns:
        The problems; empty means valid.
    """
    return replay_proposal(snapshot, recipe_ids).problems


def replay_proposal(snapshot: PlanningSnapshot, recipe_ids: list[int]) -> ReplayedPlan:
    """Replay proposed recipe ids on the snapshot with ``replay_plan``.

    Args:
        snapshot: The planning request's data.
        recipe_ids: The proposed recipe ids, in eating order.

    Returns:
        The replayed plan and its problems; unknown recipe ids are a problem with no plan.
    """
    unknown = [i for i in recipe_ids if i not in snapshot.recipes_by_id]
    if unknown:
        listed = ", ".join(str(i) for i in unknown)
        return ReplayedPlan(plan=None, problems=[f"unknown recipe id(s): {listed}"])
    request = snapshot.request
    return replay_plan(
        [snapshot.recipes_by_id[i] for i in recipe_ids],
        list(snapshot.recipes_by_id.values()),
        snapshot.batches,
        request.as_of,
        snapshot.remaining,
        snapshot.rating_summaries,
        request.meal_count,
        request.max_prep_minutes,
        request.servings_per_meal,
    )


class PlanningTool(NamedTuple):
    """A tool's name, what the model is told about it, its input model, and its function."""

    name: str
    description: str
    input_model: type[ToolModel]
    function: Callable[[PlanningSnapshot, ToolModel], ToolModel]


TOOLS = [
    PlanningTool(
        "get_planning_context",
        "Get the planning request (meal count, prep limit, servings per meal, the user's "
        "preference), today's remaining calories and macros, the stock of every recipe "
        "ingredient with use-by dates, and the top-ranked recipes with their deterministic "
        "scores. Call this first.",
        GetPlanningContextInput,
        get_planning_context,
    ),
    PlanningTool(
        "get_recipe",
        "Get one recipe's ingredients per serving against what is on hand, its prep time, "
        "whether it is within the prep limit and eligible, and its macros per serving.",
        GetRecipeInput,
        get_recipe,
    ),
    PlanningTool(
        "simulate_plan",
        "Simulate eating the given recipes in order at the requested servings per meal: what "
        "each meal uses from stock (soonest use-by first), any shortages, its macros, what is "
        "left of today's goal afterwards, and which hard constraints the sequence breaks. Use "
        "it to check a candidate plan before proposing it.",
        SimulatePlanInput,
        simulate_plan,
    ),
]
TOOLS_BY_NAME = {tool.name: tool for tool in TOOLS}


def tool_definitions() -> list[dict]:
    """Describe every tool in the shape the Anthropic Messages API expects.

    Returns:
        One ``{"name", "description", "input_schema"}`` dict per tool; each schema is generated
        from the tool's input model, so it matches what ``run_tool`` accepts.
    """
    return [
        {
            "name": tool.name,
            "description": tool.description,
            "input_schema": tool.input_model.model_json_schema(),
        }
        for tool in TOOLS
    ]


def run_tool(snapshot: PlanningSnapshot, name: str, tool_input: object) -> ToolResult:
    """Run one tool call from the model, never raising for bad input.

    Args:
        snapshot: The planning request's data.
        name: The tool the model called.
        tool_input: The model's input, as parsed JSON.

    Returns:
        The tool's JSON answer, or a JSON ToolError with ``is_error`` set when the tool is
        unknown, the input is invalid, or a recipe id does not exist.
    """
    tool = TOOLS_BY_NAME.get(name)
    if tool is None:
        return _error(f"Unknown tool {name!r}; available: {', '.join(TOOLS_BY_NAME)}.")
    try:
        validated = tool.input_model.model_validate(tool_input)
    except ValidationError as exc:
        return invalid_input_result(name, exc)
    output = tool.function(snapshot, validated)
    return ToolResult(output.model_dump_json(), is_error=isinstance(output, ToolError))


# --- Helpers. ------------------------------------------------------------------------------


def invalid_input_result(tool_name: str, exc: ValidationError) -> ToolResult:
    """Describe why a tool's input failed validation, as an error result for the model.

    Args:
        tool_name: The tool that was called.
        exc: The validation error.

    Returns:
        The ToolResult, as JSON with ``is_error`` set.
    """
    problems = "; ".join(
        f"{'.'.join(str(part) for part in e['loc']) or 'input'}: {e['msg']}" for e in exc.errors()
    )
    return _error(f"Invalid input for {tool_name}: {problems}")


def _error(message: str) -> ToolResult:
    """Wrap a message as an error result.

    Args:
        message: What was wrong.

    Returns:
        The ToolResult, as JSON with ``is_error`` set.
    """
    return ToolResult(ToolError(error=message).model_dump_json(), is_error=True)


def _unknown_recipes(recipe_ids: list[int]) -> ToolError:
    """Explain that some recipe ids do not exist.

    Args:
        recipe_ids: The unknown ids.

    Returns:
        The ToolError.
    """
    listed = ", ".join(str(i) for i in recipe_ids)
    return ToolError(error=f"Unknown recipe id(s): {listed}. Use ids from get_planning_context.")


def _within_prep_limit(snapshot: PlanningSnapshot) -> list[Recipe]:
    """List the recipes the request's prep limit allows.

    Args:
        snapshot: The planning request's data.

    Returns:
        The allowed recipes, in id order.
    """
    limit = snapshot.request.max_prep_minutes
    return [
        recipe for _, recipe in sorted(snapshot.recipes_by_id.items())
        if limit is None or recipe.prep_minutes <= limit
    ]


def _ingredient_names(snapshot: PlanningSnapshot) -> dict[int, str]:
    """Map every recipe ingredient's id to its name.

    Args:
        snapshot: The planning request's data.

    Returns:
        Ingredient id to name.
    """
    return {
        line.ingredient_id: line.ingredient.name
        for recipe in snapshot.recipes_by_id.values()
        for line in recipe.recipe_ingredients
    }


def _ingredient_units(snapshot: PlanningSnapshot) -> dict[int, str]:
    """Map every recipe ingredient's id to its unit.

    Args:
        snapshot: The planning request's data.

    Returns:
        Ingredient id to unit name (e.g. ``gram``).
    """
    return {
        line.ingredient_id: line.ingredient.canonical_unit.value
        for recipe in snapshot.recipes_by_id.values()
        for line in recipe.recipe_ingredients
    }


def _stock(snapshot: PlanningSnapshot) -> list[StockItem]:
    """Summarize stock per recipe ingredient: total, earliest use-by, and quantity due soon.

    Ingredients no recipe uses are left out; they cannot be part of a plan.

    Args:
        snapshot: The planning request's data.

    Returns:
        One StockItem per stocked recipe ingredient, in ingredient-id order.
    """
    names, units = _ingredient_names(snapshot), _ingredient_units(snapshot)
    soon = snapshot.request.as_of + timedelta(days=EXPIRING_SOON_DAYS)
    by_ingredient = defaultdict(list)
    for batch in snapshot.batches:
        if batch.ingredient_id in names and batch.quantity_remaining > 0:
            by_ingredient[batch.ingredient_id].append(batch)
    items = []
    for ingredient_id, batches in sorted(by_ingredient.items()):
        dates = [b.use_by_date for b in batches if b.use_by_date is not None]
        items.append(StockItem(
            ingredient_id=ingredient_id,
            ingredient=names[ingredient_id],
            unit=units[ingredient_id],
            on_hand=round(sum(b.quantity_remaining for b in batches), 1),
            earliest_use_by=min(dates) if dates else None,
            due_soon=round(sum(
                b.quantity_remaining for b in batches
                if b.use_by_date is not None and b.use_by_date <= soon
            ), 1),
        ))
    return items


def _ineligibility(recipe: Recipe, batches: list[SimulatedBatch]) -> str | None:
    """Explain why the recommender would exclude a recipe at this point, if it would.

    Args:
        recipe: The recipe.
        batches: The simulated stock at that point.

    Returns:
        A warning naming the missing primary ingredients, or None if the recipe is eligible.
    """
    availability = assess_recipe_availability(recipe, aggregate_inventory_by_ingredient(batches))
    if availability.is_eligible:
        return None
    missing = [
        line.recipe_ingredient.ingredient.name
        for line in availability.ingredients
        if line.is_missing and line.recipe_ingredient.role == IngredientRole.PRIMARY
    ]
    return f"ineligible: {len(missing)} primary ingredients missing ({', '.join(missing)})"


def _per_serving_macros(recipe: Recipe) -> RecipeMacros:
    """Calculate one serving's macros at the recipe's stated quantities, as macro fit does.

    Args:
        recipe: The recipe.

    Returns:
        The RecipeMacros of one serving.
    """
    total = calculate_recipe_macros(recipe)
    return RecipeMacros(*(value / recipe.servings for value in total))


def _macros(values) -> Macros | None:
    """Round a macros tuple for display.

    Args:
        values: A RecipeMacros or RemainingMacros, or None.

    Returns:
        The rounded Macros, or None.
    """
    if values is None:
        return None
    return Macros(**{field: round(value, 1) for field, value in values._asdict().items()})


def tool_result_json(result: ToolResult) -> dict:
    """Parse a tool result's JSON, for callers and tests that want the data back.

    Args:
        result: A tool result.

    Returns:
        The decoded JSON object.
    """
    return json.loads(result.content)
