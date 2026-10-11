from app.persistence.models import InventoryBatch


def add_ingredient(client, name):
    """Create an ingredient through the API.

    Args:
        client: The TestClient.
        name: The ingredient name.

    Returns:
        The new ingredient's id.
    """
    response = client.post("/ingredients", json={
        "name": name,
        "canonical_unit": "gram",
        "nutrition_base_quantity": 100,
        "calories_per_base_unit": 100,
        "protein_per_base_unit": 10,
        "carbs_per_base_unit": 10,
        "fat_per_base_unit": 1,
    })
    return response.json()["id"]


def test_add_batch_stores_full_quantity_remaining(client):
    """POST /inventory/batches returns 201 with remaining equal to the amount bought."""
    rice = add_ingredient(client, "Rice")

    response = client.post("/inventory/batches", json={
        "ingredient_id": rice,
        "quantity": 500,
        "purchased_at": "2026-10-11T09:30:00",
        "use_by_date": "2026-10-20",
    })

    assert response.status_code == 201
    assert response.json() == {
        "id": response.json()["id"],
        "ingredient_id": rice,
        "quantity_initial": 500.0,
        "quantity_remaining": 500.0,
        "purchased_at": "2026-10-11T09:30:00",
        "use_by_date": "2026-10-20",
        "depleted_at": None,
    }


def test_purchase_time_defaults_to_now(client):
    """A batch without purchased_at is stamped with the current time."""
    rice = add_ingredient(client, "Rice")

    response = client.post("/inventory/batches", json={"ingredient_id": rice, "quantity": 500})

    assert response.status_code == 201
    assert response.json()["purchased_at"]


def test_batch_for_unknown_ingredient_returns_404(client):
    """A batch referencing an ingredient that does not exist is rejected with 404."""
    response = client.post("/inventory/batches", json={"ingredient_id": 999, "quantity": 500})

    assert response.status_code == 404
    assert response.json() == {"detail": "Ingredient 999 not found"}


def test_invalid_batch_values_are_rejected_with_422(client):
    """A non-positive quantity or a timezone-aware purchase time is rejected."""
    rice = add_ingredient(client, "Rice")

    for bad in (
        {"quantity": 0},
        {"quantity": -5},
        {"quantity": 500, "purchased_at": "2026-10-11T09:30:00Z"},
    ):
        response = client.post("/inventory/batches", json={"ingredient_id": rice, **bad})
        assert response.status_code == 422, bad


def test_inventory_totals_batches_per_ingredient(client):
    """GET /inventory sums every batch of an ingredient, alphabetically by name."""
    rice = add_ingredient(client, "Rice")
    beans = add_ingredient(client, "Beans")
    for ingredient_id, quantity in ((rice, 500), (rice, 250), (beans, 400)):
        client.post(
            "/inventory/batches", json={"ingredient_id": ingredient_id, "quantity": quantity}
        )

    response = client.get("/inventory")

    assert response.status_code == 200
    assert response.json() == [
        {"ingredient_id": beans, "name": "Beans", "canonical_unit": "gram",
         "quantity_on_hand": 400.0},
        {"ingredient_id": rice, "name": "Rice", "canonical_unit": "gram",
         "quantity_on_hand": 750.0},
    ]


def test_inventory_omits_ingredients_with_nothing_left(app, client):
    """An ingredient whose batches are all used up does not appear in the inventory."""
    rice = add_ingredient(client, "Rice")
    add_ingredient(client, "Beans")  # never bought
    batch_id = client.post(
        "/inventory/batches", json={"ingredient_id": rice, "quantity": 500}
    ).json()["id"]
    # No API consumes inventory until meal confirmation (Slice 6), so empty the batch directly.
    with app.state.session_factory() as session:
        session.get(InventoryBatch, batch_id).quantity_remaining = 0
        session.commit()

    assert client.get("/inventory").json() == []
