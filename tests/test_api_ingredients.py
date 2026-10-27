from datetime import datetime

from sqlalchemy import event

from app.persistence.enums import CanonicalUnit
from app.persistence.models import Ingredient

CHICKEN = {
    "name": "Chicken breast",
    "canonical_unit": "gram",
    "nutrition_base_quantity": 100,
    "calories_per_base_unit": 165,
    "protein_per_base_unit": 31,
    "carbs_per_base_unit": 0,
    "fat_per_base_unit": 3.6,
}


def test_create_ingredient_returns_it_with_server_fields(client):
    """POST /ingredients returns 201 with the stored data, an id, and an update timestamp."""
    response = client.post("/ingredients", json=CHICKEN)

    assert response.status_code == 201
    body = response.json()
    assert body.items() >= CHICKEN.items()
    assert body["id"] > 0
    assert body["source_url"] is None
    assert body["nutrition_updated_at"]


def test_list_ingredients_is_alphabetical(client):
    """GET /ingredients returns every ingredient sorted by name."""
    client.post("/ingredients", json={**CHICKEN, "name": "Rice"})
    client.post("/ingredients", json=CHICKEN)

    response = client.get("/ingredients")

    assert response.status_code == 200
    assert [i["name"] for i in response.json()] == ["Chicken breast", "Rice"]


def test_duplicate_name_is_rejected_with_409(client):
    """Adding an ingredient whose name already exists returns 409 and stores nothing new."""
    client.post("/ingredients", json=CHICKEN)

    response = client.post("/ingredients", json=CHICKEN)

    assert response.status_code == 409
    assert len(client.get("/ingredients").json()) == 1


def test_losing_a_same_name_race_is_rejected_with_409(app, client):
    """An ingredient whose name another request commits after the duplicate check gets 409."""

    def other_request_commits_first(*_args):
        """Commit the same ingredient in another session, as a concurrent request would.

        Runs as this request flushes its insert: after its duplicate check found nothing.

        Args:
            *_args: The event's arguments; unused.
        """
        with app.state.session_factory() as other_session:
            other_session.add(Ingredient(
                **{**CHICKEN, "canonical_unit": CanonicalUnit.GRAM},
                nutrition_updated_at=datetime.now(),
            ))
            other_session.commit()

    event.listen(app.state.session_factory, "before_flush", other_request_commits_first, once=True)
    response = client.post("/ingredients", json=CHICKEN)

    assert response.status_code == 409
    assert response.json() == {"detail": "Ingredient 'Chicken breast' already exists"}
    assert len(client.get("/ingredients").json()) == 1


def test_invalid_nutrition_values_are_rejected_with_422(client):
    """A zero base quantity, a negative macro, or a blank name is rejected before saving."""
    for bad in (
        {"nutrition_base_quantity": 0},
        {"fat_per_base_unit": -1},
        {"name": "   "},
        {"canonical_unit": "cup"},
    ):
        response = client.post("/ingredients", json={**CHICKEN, **bad})
        assert response.status_code == 422, bad

    assert client.get("/ingredients").json() == []


def test_infinite_macro_is_rejected_with_422(client):
    """Infinity, which Python's JSON parser accepts, is not a valid macro value."""
    body = '{"name": "X", "canonical_unit": "gram", "nutrition_base_quantity": 100, ' \
        '"calories_per_base_unit": Infinity, "protein_per_base_unit": 0, ' \
        '"carbs_per_base_unit": 0, "fat_per_base_unit": 0}'

    response = client.post(
        "/ingredients", content=body, headers={"Content-Type": "application/json"}
    )

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "calories_per_base_unit"]
