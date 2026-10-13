from datetime import date, datetime

import pytest

from app.persistence.models import MealLog

KEY = "8f14e45f-ceea-4c1e-9a6b-2f1c3e5d7a90"


@pytest.fixture
def stir_fry(client):
    """A 2-serving recipe with 300 g chicken and 200 g rice in stock (macros per 100 g).

    Args:
        client: The TestClient.

    Returns:
        The recipe's id.
    """
    ids = {}
    for name, calories in (("Chicken", 165), ("Rice", 130)):
        ids[name] = client.post("/ingredients", json={
            "name": name, "canonical_unit": "gram", "nutrition_base_quantity": 100,
            "calories_per_base_unit": calories, "protein_per_base_unit": 10,
            "carbs_per_base_unit": 10, "fat_per_base_unit": 1,
        }).json()["id"]
    client.post("/inventory/batches", json={"ingredient_id": ids["Chicken"], "quantity": 300})
    client.post("/inventory/batches", json={"ingredient_id": ids["Rice"], "quantity": 200})
    return client.post("/recipes", json={
        "name": "Stir fry", "prep_minutes": 20, "servings": 2,
        "ingredients": [
            {"ingredient_id": ids["Chicken"], "quantity": 200, "role": "primary"},
            {"ingredient_id": ids["Rice"], "quantity": 300, "role": "supporting"},
        ],
    }).json()["id"]


def confirm(client, recipe_id, key=None, **body):
    """Confirm one serving of a recipe at a fixed time, with optional overrides.

    Args:
        client: The TestClient.
        recipe_id: The recipe to confirm.
        key: Optional value for the ``Idempotency-Key`` header.
        **body: Request fields that replace the defaults.

    Returns:
        The HTTP response.
    """
    return client.post(
        f"/recipes/{recipe_id}/confirm",
        json={"servings": 1, "consumed_at": "2026-10-11T19:00:00", **body},
        headers={"Idempotency-Key": key} if key is not None else {},
    )


def on_hand(client):
    """Return the quantity on hand per ingredient name.

    Args:
        client: The TestClient.

    Returns:
        Mapping of ingredient name to total quantity on hand.
    """
    return {item["name"]: item["quantity_on_hand"] for item in client.get("/inventory").json()}


def test_confirm_logs_one_serving_and_consumes_inventory(client, stir_fry):
    """Confirming one of two servings logs and consumes half the recipe."""
    response = confirm(client, stir_fry)

    assert response.status_code == 201
    meal = response.json()
    assert meal["recipe_id"] == stir_fry
    assert meal["name"] == "Stir fry"
    assert meal["consumed_at"] == "2026-10-11T19:00:00"
    assert meal["calories"] == pytest.approx(165 + 1.5 * 130)
    assert meal["idempotency_key"] is None
    assert [(i["name"], i["quantity"]) for i in meal["ingredients"]] == [
        ("Chicken", 100), ("Rice", 150),
    ]
    assert on_hand(client) == {"Chicken": 200, "Rice": 50}


def test_retry_with_the_same_key_returns_the_original_meal(client, stir_fry):
    """A replayed Idempotency-Key returns 200 with the first meal and consumes nothing more."""
    first = confirm(client, stir_fry, key=KEY)

    retry = confirm(client, stir_fry, key=KEY, servings=0.5)

    assert first.status_code == 201
    assert first.json()["idempotency_key"] == KEY
    assert retry.status_code == 200
    assert retry.json() == first.json()
    assert on_hand(client) == {"Chicken": 200, "Rice": 50}
    assert len(client.get("/meal-logs", params={"consumed_on": "2026-10-11"}).json()) == 1


def test_without_a_key_every_confirmation_logs_a_meal(client, stir_fry):
    """Two confirmations without an Idempotency-Key header are two meals."""
    confirm(client, stir_fry, servings=0.5)
    confirm(client, stir_fry, servings=0.5)

    assert len(client.get("/meal-logs", params={"consumed_on": "2026-10-11"}).json()) == 2
    assert on_hand(client) == {"Chicken": 200, "Rice": 50}


def test_shortfall_returns_409_with_details_and_writes_nothing(client, stir_fry):
    """Without the override, a shortfall is reported per ingredient and nothing is logged."""
    response = confirm(client, stir_fry, key=KEY, servings=2)

    assert response.status_code == 409
    assert response.json() == {"detail": {
        "message": "Insufficient inventory",
        "shortfalls": [{
            "ingredient_id": response.json()["detail"]["shortfalls"][0]["ingredient_id"],
            "name": "Rice", "quantity_needed": 300.0, "quantity_available": 200.0,
        }],
    }}
    assert client.get("/meal-logs", params={"consumed_on": "2026-10-11"}).json() == []
    assert on_hand(client) == {"Chicken": 300, "Rice": 200}


def test_shortfall_override_consumes_only_what_is_available(client, stir_fry):
    """With allow_shortfall, the meal is logged using only the inventory on hand."""
    response = confirm(client, stir_fry, servings=2, allow_shortfall=True)

    assert response.status_code == 201
    assert [(i["name"], i["quantity"]) for i in response.json()["ingredients"]] == [
        ("Chicken", 200), ("Rice", 200),
    ]
    assert on_hand(client) == {"Chicken": 100}


def test_unknown_recipe_returns_404(client):
    """Confirming a recipe that does not exist returns 404."""
    response = confirm(client, 999)

    assert response.status_code == 404
    assert response.json() == {"detail": "Recipe 999 not found"}


def test_invalid_confirmations_are_rejected_with_422(client, stir_fry):
    """Non-positive servings, timezone-aware times, and blank names are rejected."""
    for bad in (
        {"servings": 0},
        {"consumed_at": "2026-10-11T19:00:00Z"},
        {"name": ""},
    ):
        assert confirm(client, stir_fry, **bad).status_code == 422, bad

    assert on_hand(client) == {"Chicken": 300, "Rice": 200}


def test_malformed_idempotency_key_header_is_rejected_with_422(client, stir_fry):
    """An Idempotency-Key header that is not a UUID is rejected before anything is consumed."""
    response = confirm(client, stir_fry, key="not-a-uuid")

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["header", "Idempotency-Key"]
    assert on_hand(client) == {"Chicken": 300, "Rice": 200}


def test_failed_shortfall_does_not_use_up_the_key(client, stir_fry):
    """A rejected confirmation leaves its key unused, so a later valid request can use it."""
    rejected = confirm(client, stir_fry, key=KEY, servings=2)

    accepted = confirm(client, stir_fry, key=KEY, servings=2, allow_shortfall=True)

    assert rejected.status_code == 409
    assert accepted.status_code == 201
    assert accepted.json()["idempotency_key"] == KEY
    assert on_hand(client) == {"Chicken": 100}


def test_idempotency_key_in_the_body_is_not_part_of_the_contract(client, stir_fry):
    """A body idempotency_key field is ignored like any unknown field: no replay protection."""
    first = confirm(client, stir_fry, servings=0.5, idempotency_key=KEY)
    second = confirm(client, stir_fry, servings=0.5, idempotency_key=KEY)

    assert (first.status_code, second.status_code) == (201, 201)
    assert first.json()["idempotency_key"] is None
    assert len(client.get("/meal-logs", params={"consumed_on": "2026-10-11"}).json()) == 2


def test_meal_logs_lists_one_day_in_order(client, stir_fry):
    """GET /meal-logs returns only the requested day's meals, earliest first."""
    confirm(client, stir_fry, servings=0.5, consumed_at="2026-10-11T19:00:00", name="Dinner")
    confirm(client, stir_fry, servings=0.5, consumed_at="2026-10-11T08:00:00", name="Breakfast")
    confirm(client, stir_fry, servings=0.5, consumed_at="2026-10-12T08:00:00", name="Tomorrow")

    meals = client.get("/meal-logs", params={"consumed_on": "2026-10-11"}).json()

    assert [m["name"] for m in meals] == ["Breakfast", "Dinner"]


def test_meal_logs_default_to_today(client, stir_fry):
    """Without consumed_on, today's meals are listed."""
    confirm(client, stir_fry, consumed_at=f"{date.today()}T12:00:00")

    assert len(client.get("/meal-logs").json()) == 1


def test_rating_a_meal_returns_201_and_shows_on_the_meal(client, stir_fry):
    """A rating is stored and appears on the meal in GET /meal-logs."""
    meal_id = confirm(client, stir_fry).json()["id"]

    response = client.post(f"/meal-logs/{meal_id}/feedback", json={"rating": 4})

    assert response.status_code == 201
    assert response.json() == {"id": response.json()["id"], "meal_log_id": meal_id, "rating": 4}
    meals = client.get("/meal-logs", params={"consumed_on": "2026-10-11"}).json()
    assert meals[0]["rating"] == 4


def test_unrated_meal_shows_no_rating(client, stir_fry):
    """A meal nobody has rated reports rating null."""
    assert confirm(client, stir_fry).json()["rating"] is None


def test_second_rating_is_rejected_with_409(client, stir_fry):
    """A meal can be rated once; a second rating leaves the first unchanged."""
    meal_id = confirm(client, stir_fry).json()["id"]
    client.post(f"/meal-logs/{meal_id}/feedback", json={"rating": 4})

    response = client.post(f"/meal-logs/{meal_id}/feedback", json={"rating": 1})

    assert response.status_code == 409
    assert response.json() == {"detail": f"Meal log {meal_id} is already rated"}
    meals = client.get("/meal-logs", params={"consumed_on": "2026-10-11"}).json()
    assert meals[0]["rating"] == 4


def test_rating_an_unknown_meal_returns_404(client):
    """Rating a meal that does not exist returns 404."""
    response = client.post("/meal-logs/999/feedback", json={"rating": 3})

    assert response.status_code == 404
    assert response.json() == {"detail": "Meal log 999 not found"}


def test_ratings_must_be_whole_numbers_from_1_to_5(client, stir_fry):
    """Out-of-range, fractional, string, and boolean ratings are rejected with 422."""
    meal_id = confirm(client, stir_fry).json()["id"]

    for bad in (0, 6, 4.5, 4.0, "4", True):
        response = client.post(f"/meal-logs/{meal_id}/feedback", json={"rating": bad})
        assert response.status_code == 422, bad


def test_manual_meals_can_be_rated(app, client):
    """A meal not made from a recipe can still be rated."""
    with app.state.session_factory() as session:
        meal = MealLog(name="Takeout", consumed_at=datetime(2026, 10, 11, 20, 0),
                       calories=900, protein=30, carbs=100, fat=40)
        session.add(meal)
        session.commit()
        meal_id = meal.id

    response = client.post(f"/meal-logs/{meal_id}/feedback", json={"rating": 5})

    assert response.status_code == 201


def test_rating_feeds_the_recipes_enjoyment_score(client, stir_fry):
    """Rating a recipe's meal changes that recipe's enjoyment in recommendations."""
    meal_id = confirm(client, stir_fry, servings=0.5).json()["id"]

    client.post(f"/meal-logs/{meal_id}/feedback", json={"rating": 5})

    recommendations = client.get("/recommendations", params={"as_of": "2026-10-11"}).json()
    assert recommendations[0]["enjoyment"] == {
        "score": 1.0, "average_rating": 5.0, "rating_count": 1,
    }
