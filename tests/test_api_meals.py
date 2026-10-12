from datetime import date

import pytest

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


def confirm(client, recipe_id, **body):
    """Confirm one serving of a recipe at a fixed time, with optional overrides.

    Args:
        client: The TestClient.
        recipe_id: The recipe to confirm.
        **body: Request fields that replace the defaults.

    Returns:
        The HTTP response.
    """
    return client.post(
        f"/recipes/{recipe_id}/confirm",
        json={"servings": 1, "consumed_at": "2026-10-11T19:00:00", **body},
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
    """A replayed key returns 200 with the first meal and consumes nothing more."""
    first = confirm(client, stir_fry, idempotency_key=KEY)

    retry = confirm(client, stir_fry, idempotency_key=KEY, servings=0.5)

    assert first.status_code == 201
    assert retry.status_code == 200
    assert retry.json() == first.json()
    assert on_hand(client) == {"Chicken": 200, "Rice": 50}
    assert len(client.get("/meal-logs", params={"consumed_on": "2026-10-11"}).json()) == 1


def test_without_a_key_every_confirmation_logs_a_meal(client, stir_fry):
    """Two confirmations without a key are two meals."""
    confirm(client, stir_fry, servings=0.5)
    confirm(client, stir_fry, servings=0.5)

    assert len(client.get("/meal-logs", params={"consumed_on": "2026-10-11"}).json()) == 2
    assert on_hand(client) == {"Chicken": 200, "Rice": 50}


def test_shortfall_returns_409_with_details_and_writes_nothing(client, stir_fry):
    """Without the override, a shortfall is reported per ingredient and nothing is logged."""
    response = confirm(client, stir_fry, servings=2, idempotency_key=KEY)

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
    """Non-positive servings, timezone-aware times, bad keys, and blank names are rejected."""
    for bad in (
        {"servings": 0},
        {"consumed_at": "2026-10-11T19:00:00Z"},
        {"idempotency_key": "not-a-uuid"},
        {"name": ""},
    ):
        assert confirm(client, stir_fry, **bad).status_code == 422, bad

    assert on_hand(client) == {"Chicken": 300, "Rice": 200}


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
