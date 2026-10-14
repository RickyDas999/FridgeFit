from datetime import datetime

import pytest

from app.persistence.models import MealFeedback, MealLog

AS_OF = "2026-10-11"


def add_ingredient(client, name, calories=100):
    """Create an ingredient with macros per 100 g through the API.

    Args:
        client: The TestClient.
        name: The ingredient name.
        calories: Calories per 100 g.

    Returns:
        The new ingredient's id.
    """
    return client.post("/ingredients", json={
        "name": name, "canonical_unit": "gram", "nutrition_base_quantity": 100,
        "calories_per_base_unit": calories, "protein_per_base_unit": 10,
        "carbs_per_base_unit": 10, "fat_per_base_unit": 1,
    }).json()["id"]


def add_recipe(client, name, *lines, servings=1):
    """Create a recipe through the API.

    Args:
        client: The TestClient.
        name: The recipe name.
        *lines: ``(ingredient_id, quantity, role)`` tuples.
        servings: How many servings the recipe makes.

    Returns:
        The new recipe's id.
    """
    return client.post("/recipes", json={
        "name": name, "prep_minutes": 10, "servings": servings,
        "ingredients": [
            {"ingredient_id": i, "quantity": q, "role": role} for i, q, role in lines
        ],
    }).json()["id"]


def add_batch(client, ingredient_id, quantity, use_by_date=None):
    """Record a grocery purchase through the API.

    Args:
        client: The TestClient.
        ingredient_id: The ingredient bought.
        quantity: Amount bought.
        use_by_date: Optional use-by date, as ``YYYY-MM-DD``.

    Returns:
        The new batch's id.
    """
    return client.post("/inventory/batches", json={
        "ingredient_id": ingredient_id, "quantity": quantity, "use_by_date": use_by_date,
        "purchased_at": "2026-10-01T10:00:00",
    }).json()["id"]


def log_meal(app, recipe_id, consumed_at, rating=None):
    """Insert a MealLog (and optional rating) directly; their endpoints come in Slices 6-7.

    Args:
        app: The FastAPI application, for its session factory.
        recipe_id: The recipe the meal was made from.
        consumed_at: When it was eaten.
        rating: Optional 1-5 rating.
    """
    with app.state.session_factory() as session:
        meal = MealLog(name="Meal", recipe_id=recipe_id, consumed_at=consumed_at,
                       calories=0, protein=0, carbs=0, fat=0)
        session.add(meal)
        if rating is not None:
            session.add(MealFeedback(meal_log=meal, rating=rating))
        session.commit()


def recommend(client, as_of=AS_OF):
    """Fetch recommendations, asserting success.

    Args:
        client: The TestClient.
        as_of: The calendar day to request.

    Returns:
        The response body, keyed by recipe name.
    """
    response = client.get("/recommendations", params={"as_of": as_of})
    assert response.status_code == 200
    return {item["name"]: item for item in response.json()}


def test_no_recipes_means_no_recommendations(client):
    """With nothing stored, recommendations are an empty list."""
    assert recommend(client) == {}


def test_recipes_are_ranked_and_reported_per_serving(client):
    """Recipes rank highest first, judged per serving; ineligible ones are left out."""
    rice, beans, corn, leeks = (
        add_ingredient(client, n) for n in ("Rice", "Beans", "Corn", "Leeks")
    )
    add_batch(client, rice, 100)
    add_batch(client, beans, 50)
    add_recipe(client, "Rice bowl", (rice, 400, "primary"), servings=4)
    add_recipe(client, "Beans and rice", (rice, 100, "primary"), (beans, 100, "primary"))
    # Two PRIMARY ingredients with no stock: ineligible.
    add_recipe(client, "Corn and leek soup", (corn, 100, "primary"), (leeks, 50, "primary"))

    response = client.get("/recommendations", params={"as_of": AS_OF}).json()

    assert [r["name"] for r in response] == ["Rice bowl", "Beans and rice"]
    bowl = response[0]
    assert bowl["availability"]["ingredients"] == [{
        "ingredient_id": rice, "name": "Rice", "role": "primary", "quantity_per_serving": 100.0,
        "quantity_on_hand": 100.0, "fraction_available": 1.0, "is_missing": False,
    }]
    assert bowl["macro_fit"] is None
    assert bowl["enjoyment"] == {"score": 0.5, "average_rating": None, "rating_count": 0}
    assert bowl["recent_frequency"] == {"times_eaten_recently": 0, "last_eaten_on": None}


def test_macro_fit_is_scored_once_a_goal_applies(client):
    """With a nutrition goal in effect, macro fit is reported for one serving."""
    rice = add_ingredient(client, "Rice", calories=130)
    add_batch(client, rice, 500)
    add_recipe(client, "Rice bowl", (rice, 400, "primary"), servings=2)
    client.post("/nutrition-goals", json={
        "calories": 2000, "protein": 150, "carbs": 200, "fat": 70, "effective_date": "2026-10-01",
    })

    macro_fit = recommend(client)["Rice bowl"]["macro_fit"]

    assert 0 <= macro_fit["score"] <= 1
    assert macro_fit["per_serving"]["calories"] == pytest.approx(260)


def test_expired_batches_are_surfaced_as_warnings(client):
    """A batch past its use-by date is listed by id, and still counts as inventory."""
    rice = add_ingredient(client, "Rice")
    expired = add_batch(client, rice, 100, use_by_date="2026-10-09")
    add_recipe(client, "Rice bowl", (rice, 100, "primary"))

    bowl = recommend(client)["Rice bowl"]

    assert bowl["expiry_urgency"]["expired_batches"] == [
        {"batch_id": expired, "ingredient_id": rice, "use_by_date": "2026-10-09"}
    ]
    assert bowl["availability"]["ingredients"][0]["fraction_available"] == 1.0


def test_each_ingredient_reports_when_it_needs_using(client):
    """Every recipe ingredient gets its soonest unexpired use-by date and an expiring-soon flag."""
    rice, beans, corn = (add_ingredient(client, n) for n in ("Rice", "Beans", "Corn"))
    add_batch(client, rice, 100, use_by_date="2026-10-12")  # tomorrow: expiring soon
    add_batch(client, beans, 100, use_by_date="2026-10-20")
    add_batch(client, beans, 100, use_by_date="2026-10-09")  # expired: not the reported date
    add_batch(client, corn, 100)  # undated
    add_recipe(
        client, "Bowl", (rice, 100, "primary"), (beans, 100, "primary"), (corn, 100, "supporting")
    )

    expiry = recommend(client)["Bowl"]["expiry_urgency"]

    assert expiry["ingredients"] == [
        {"ingredient_id": rice, "use_by_date": "2026-10-12", "expiring_soon": True},
        {"ingredient_id": beans, "use_by_date": "2026-10-20", "expiring_soon": False},
        {"ingredient_id": corn, "use_by_date": None, "expiring_soon": False},
    ]


def test_recent_frequency_and_enjoyment_come_from_meal_history(app, client):
    """Recent count uses the 7-day window, last eaten uses all history, ratings feed enjoyment."""
    rice = add_ingredient(client, "Rice")
    add_batch(client, rice, 1000)
    bowl_id = add_recipe(client, "Rice bowl", (rice, 100, "primary"))
    old_id = add_recipe(client, "Old favorite", (rice, 100, "primary"))
    log_meal(app, bowl_id, datetime(2026, 10, 5, 12, 0), rating=5)   # first day of the window
    log_meal(app, bowl_id, datetime(2026, 10, 11, 23, 59), rating=4)  # as_of
    log_meal(app, bowl_id, datetime(2026, 10, 12, 8, 0))              # after as_of: ignored
    log_meal(app, old_id, datetime(2026, 9, 1, 19, 0))                # outside the window

    result = recommend(client)

    assert result["Rice bowl"]["recent_frequency"] == {
        "times_eaten_recently": 2, "last_eaten_on": AS_OF,
    }
    assert result["Old favorite"]["recent_frequency"] == {
        "times_eaten_recently": 0, "last_eaten_on": "2026-09-01",
    }
    assert result["Rice bowl"]["enjoyment"]["average_rating"] == pytest.approx(4.5)


def test_as_of_defaults_to_today_and_must_be_a_date(client):
    """Without as_of today is used; a non-date as_of is rejected with 422."""
    assert client.get("/recommendations").status_code == 200
    assert client.get("/recommendations", params={"as_of": "today"}).status_code == 422


def test_recommendations_run_a_fixed_number_of_queries(app, client, count_queries):
    """GET /recommendations does not run extra queries per recipe, ingredient, or rating."""
    def add_rated_recipe(name):
        """Add a stocked one-ingredient recipe with one rated meal yesterday."""
        ingredient = add_ingredient(client, f"{name} base")
        add_batch(client, ingredient, 500)
        recipe = add_recipe(client, name, (ingredient, 100, "primary"))
        log_meal(app, recipe, datetime(2026, 10, 10, 19, 0), rating=4)

    add_rated_recipe("First")
    with count_queries() as few:
        recommend(client)

    for n in range(3):
        add_rated_recipe(f"Recipe {n}")
    with count_queries() as many:
        assert len(recommend(client)) == 4

    assert many[0] == few[0]
