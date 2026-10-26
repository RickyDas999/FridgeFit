from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class EvaluationModel(BaseModel):
    """Base for evaluation results: immutable, finite numbers only, and no unknown fields."""

    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)


class MacroAmounts(EvaluationModel):
    """Calories (kcal) and protein, carbs, and fat (g)."""

    calories: float
    protein: float
    carbs: float
    fat: float


class Shortfall(EvaluationModel):
    """An ingredient a planned meal needed more of than was on hand."""

    meal_index: int = Field(ge=0)
    ingredient: str
    quantity_needed: float = Field(gt=0)
    quantity_available: float = Field(ge=0)


class MacroResult(EvaluationModel):
    """How the day ends against its goal, judged the way macro fit judges a meal.

    Calories, carbs, and fat should stay under the goal; protein should reach it, and up to
    macro fit's ``PROTEIN_ACCEPTABLE_EXCESS`` (1.5) times it is fine.
    """

    goal: MacroAmounts
    # Goal minus everything eaten and planned: positive is under the goal, negative is over.
    end_of_day_remaining: MacroAmounts
    calories_over: float = Field(ge=0)
    carbs_over: float = Field(ge=0)
    fat_over: float = Field(ge=0)
    protein_short: float = Field(ge=0)
    protein_excess: float = Field(ge=0)


class ExpiringFoodResult(EvaluationModel):
    """How much of the stock due within the expiring-soon window the plan uses."""

    expiring_batches: int = Field(ge=0)
    expiring_batches_used_up: int = Field(ge=0)
    # Mean share of each expiring batch's quantity the plan uses; None when nothing is expiring.
    share_used: float | None = Field(ge=0, le=1)


class RubricCheck(EvaluationModel):
    """One machine-checkable rule standing in for a soft preference."""

    rule: str
    passed: bool
    detail: str


class PreferenceResult(EvaluationModel):
    """The scenario's soft preference and how the plan did on its rubric."""

    text: str | None
    checks: list[RubricCheck]


class AttemptResult(EvaluationModel):
    """How one AI planning attempt ran and what it cost; absent for the baseline."""

    source: str
    outcome: str
    fallback_reason: str | None
    rejected_plans: int = Field(ge=0)
    model_calls: int = Field(ge=0)
    tool_calls: int = Field(ge=0)
    invalid_tool_calls: int = Field(ge=0)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cache_read_input_tokens: int = Field(ge=0)
    cache_creation_input_tokens: int = Field(ge=0)
    model_seconds: float = Field(ge=0)
    total_seconds: float = Field(ge=0)
    # Derived from the raw tokens and the evaluation price table; None for an unpriced model.
    estimated_cost_usd: float | None = Field(ge=0)


class ScenarioResult(EvaluationModel):
    """Every metric for one planner on one scenario (and, for AI runs, one repeat)."""

    scenario_id: str
    description: str
    meals_requested: int = Field(ge=1)
    meals_planned: int = Field(ge=0)
    planned_recipes: list[str]
    hard_constraint_violations: list[str]
    meals_with_shortfalls: int = Field(ge=0)
    shortfalls: list[Shortfall]
    macros: MacroResult | None
    expiring_food: ExpiringFoodResult
    preference: PreferenceResult
    run: int = Field(default=1, ge=1)
    ai: AttemptResult | None = None


class AISummary(EvaluationModel):
    """How the AI attempts of one configuration went, across scenarios and repeats."""

    attempts: int = Field(ge=0)
    ai_plans_used: int = Field(ge=0)
    fallbacks: int = Field(ge=0)
    corrected_plans_used: int = Field(ge=0)
    invalid_tool_calls: int = Field(ge=0)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    mean_total_seconds: float | None = Field(ge=0)
    max_total_seconds: float | None = Field(ge=0)
    estimated_cost_usd: float | None = Field(ge=0)


class RunSummary(EvaluationModel):
    """Aggregates across all scenarios of one run."""

    scenarios: int = Field(ge=0)
    complete_plans: int = Field(ge=0)
    hard_constraint_compliant: int = Field(ge=0)
    plans_without_shortfalls: int = Field(ge=0)
    total_calories_over: float = Field(ge=0)
    total_protein_short: float = Field(ge=0)
    mean_expiring_share_used: float | None = Field(ge=0, le=1)
    rubric_checks_passed: int = Field(ge=0)
    rubric_checks: int = Field(ge=0)
    ai: AISummary | None = None


class EvaluationRun(EvaluationModel):
    """One planner's results on the scenario set; what the evaluation script writes."""

    planner: str
    created_at: datetime
    scenario_date: date
    results: list[ScenarioResult]
    summary: RunSummary
    # Why the run ended before every scenario and repeat ran (e.g. the spending cap), if it did.
    stopped_early: str | None = None
