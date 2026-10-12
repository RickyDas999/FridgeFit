from datetime import date, datetime

import pytest

from app.persistence.models import MealLog

GOAL = {"calories": 2000, "protein": 150, "carbs": 200, "fat": 70, "effective_date": "2026-10-01"}


def log_meal(app, consumed_at, calories, protein, carbs, fat):
    """Insert a MealLog directly; no API logs meals until meal confirmation (Slice 6).

    Args:
        app: The FastAPI application, for its session factory.
        consumed_at: When the meal was eaten.
        calories: The meal's calories.
        protein: The meal's protein.
        carbs: The meal's carbohydrates.
        fat: The meal's fat.
    """
    with app.state.session_factory() as session:
        session.add(MealLog(
            name="Meal", consumed_at=consumed_at,
            calories=calories, protein=protein, carbs=carbs, fat=fat,
        ))
        session.commit()


def test_create_goal_returns_it(client):
    """POST /nutrition-goals returns 201 with the stored goal."""
    response = client.post("/nutrition-goals", json=GOAL)

    assert response.status_code == 201
    assert response.json() == {"id": response.json()["id"], **GOAL}


def test_second_goal_on_the_same_date_is_rejected_with_409(client):
    """Only one goal may start on a given date."""
    client.post("/nutrition-goals", json=GOAL)

    response = client.post("/nutrition-goals", json={**GOAL, "calories": 1800})

    assert response.status_code == 409
    assert response.json() == {"detail": "A goal already starts on 2026-10-01"}


def test_invalid_goals_are_rejected_with_422(client):
    """Negative targets and malformed dates are rejected."""
    for bad in ({"protein": -1}, {"effective_date": "October 1"}, {"effective_date": None}):
        response = client.post("/nutrition-goals", json={**GOAL, **bad})
        assert response.status_code == 422, bad


def test_state_without_a_goal_is_a_normal_response(client):
    """With no goal in effect, nutrition state returns 200 with goal and remaining null."""
    response = client.get("/nutrition-state", params={"as_of": "2026-10-11"})

    assert response.status_code == 200
    assert response.json() == {"as_of": "2026-10-11", "goal": None, "remaining": None}


def test_remaining_subtracts_only_that_days_meals(app, client):
    """Remaining macros are the goal minus meals eaten on the requested calendar day."""
    client.post("/nutrition-goals", json=GOAL)
    log_meal(app, datetime(2026, 10, 11, 8, 0), 500, 30, 60, 20)
    log_meal(app, datetime(2026, 10, 11, 23, 59), 700, 50, 80, 25)
    log_meal(app, datetime(2026, 10, 10, 12, 0), 900, 60, 90, 30)  # the day before

    response = client.get("/nutrition-state", params={"as_of": "2026-10-11"})

    assert response.json()["remaining"] == pytest.approx(
        {"calories": 800, "protein": 70, "carbs": 60, "fat": 25}
    )


def test_day_boundaries_are_midnight_to_midnight(app, client):
    """Meals at 00:00 and 23:59:59 count toward the day; 00:00 the next day does not."""
    client.post("/nutrition-goals", json=GOAL)
    log_meal(app, datetime(2026, 10, 11, 0, 0), 100, 0, 0, 0)
    log_meal(app, datetime(2026, 10, 11, 23, 59, 59), 200, 0, 0, 0)
    log_meal(app, datetime(2026, 10, 12, 0, 0), 400, 0, 0, 0)
    log_meal(app, datetime(2026, 10, 10, 23, 59, 59), 800, 0, 0, 0)

    response = client.get("/nutrition-state", params={"as_of": "2026-10-11"})

    assert response.json()["remaining"]["calories"] == pytest.approx(2000 - 100 - 200)


def test_state_uses_the_latest_goal_on_or_before_the_date(client):
    """A newer goal applies from its effective date; a future goal is ignored."""
    goals = ((2000, "2026-10-01"), (1800, "2026-10-05"), (1500, "2026-11-01"))
    for calories, effective_date in goals:
        client.post(
            "/nutrition-goals",
            json={**GOAL, "calories": calories, "effective_date": effective_date},
        )

    goal = client.get("/nutrition-state", params={"as_of": "2026-10-11"}).json()["goal"]

    assert goal["calories"] == 1800
    assert goal["effective_date"] == "2026-10-05"


def test_as_of_defaults_to_today(client):
    """Without as_of, nutrition state is reported for the server's current date."""
    response = client.get("/nutrition-state")

    assert response.status_code == 200
    assert response.json()["as_of"] == date.today().isoformat()


def test_non_date_as_of_is_rejected_with_422(client):
    """An as_of that is not a YYYY-MM-DD date is rejected."""
    assert client.get("/nutrition-state", params={"as_of": "today"}).status_code == 422
