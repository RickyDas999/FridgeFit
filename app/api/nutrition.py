from datetime import date

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.recipes import MacrosResponse
from app.api.session import SessionDep
from app.application.nutrition import get_nutrition_state
from app.persistence.models import NutritionGoal

router = APIRouter(tags=["nutrition"])


class GoalCreate(BaseModel):
    """Request body for a new daily nutrition goal."""

    # Python's JSON parser accepts Infinity and NaN; neither is a real target.
    model_config = ConfigDict(allow_inf_nan=False)

    calories: float = Field(ge=0)
    protein: float = Field(ge=0)
    carbs: float = Field(ge=0)
    fat: float = Field(ge=0)
    effective_date: date = Field(description="First day the goal applies; may be in the future.")


class GoalResponse(BaseModel):
    """One stored nutrition goal."""

    # Lets model_validate read attributes from a NutritionGoal ORM object.
    model_config = ConfigDict(from_attributes=True)

    id: int
    calories: float
    protein: float
    carbs: float
    fat: float
    effective_date: date


class NutritionStateResponse(BaseModel):
    """The goal in effect on a day and what is left of it."""

    as_of: date
    goal: GoalResponse | None = Field(description="None when no goal is effective yet.")
    remaining: MacrosResponse | None = Field(
        description="Goal minus that day's meals; negative once a target is exceeded."
    )


@router.post("/nutrition-goals", status_code=201)
def create_goal(body: GoalCreate, session: SessionDep) -> GoalResponse:
    """Add a nutrition goal; earlier goals are kept as history.

    Args:
        body: The goal's targets and effective date.
        session: The request's database session.

    Returns:
        The stored goal.

    Raises:
        HTTPException: 409 if a goal already starts on that date.
    """
    existing = session.scalar(
        select(NutritionGoal).where(NutritionGoal.effective_date == body.effective_date)
    )
    if existing is not None:
        raise HTTPException(
            status_code=409, detail=f"A goal already starts on {body.effective_date}"
        )

    goal = NutritionGoal(**body.model_dump())
    session.add(goal)
    session.commit()
    return GoalResponse.model_validate(goal)


@router.get("/nutrition-state")
def read_nutrition_state(
    session: SessionDep, as_of: date | None = None
) -> NutritionStateResponse:
    """Return the goal in effect on a calendar day and the macros left in it.

    Having no goal yet is a normal state, not an error.

    Args:
        session: The request's database session.
        as_of: The calendar day, as ``YYYY-MM-DD``. Defaults to today on the server's clock.

    Returns:
        The day's nutrition state.
    """
    as_of = as_of or date.today()
    state = get_nutrition_state(session, as_of)
    return NutritionStateResponse(
        as_of=as_of,
        goal=GoalResponse.model_validate(state.goal) if state.goal else None,
        remaining=MacrosResponse(**state.remaining._asdict()) if state.remaining else None,
    )
