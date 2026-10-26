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


class ScenarioResult(EvaluationModel):
    """Every metric for one planner on one scenario."""

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


class EvaluationRun(EvaluationModel):
    """One planner's results on the scenario set; what the evaluation script writes."""

    planner: str
    created_at: datetime
    scenario_date: date
    results: list[ScenarioResult]
    summary: RunSummary
