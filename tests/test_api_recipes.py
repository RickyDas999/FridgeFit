import pytest
from sqlalchemy import event

from app.persistence.enums import IngredientRole
from app.persistence.models import Recipe, RecipeIngredient


def add_ingredient(client, name, calories, protein, carbs, fat):
    """Create an ingredient with macros per 100 g through the API.

    Args:
        client: The TestClient.
        name: The ingredient name.
        calories: Calories per 100 g.
        protein: Protein per 100 g.
        carbs: Carbohydrates per 100 g.
        fat: Fat per 100 g.

    Returns:
        The new ingredient's id.
    """
    response = client.post("/ingredients", json={
        "name": name,
        "canonical_unit": "gram",
        "nutrition_base_quantity": 100,
        "calories_per_base_unit": calories,
        "protein_per_base_unit": protein,
        "carbs_per_base_unit": carbs,
        "fat_per_base_unit": fat,
    })
    return response.json()["id"]


@pytest.fixture
def stir_fry(client):
    """A valid recipe request body using two freshly created ingredients.

    Args:
        client: The TestClient.

    Returns:
        The request body for a 2-serving chicken and rice recipe.
    """
    chicken = add_ingredient(client, "Chicken", 165, 31, 0, 3.6)
    rice = add_ingredient(client, "Rice", 130, 2.7, 28, 0.3)
    return {
        "name": "Chicken stir fry",
        "instructions": ["Cook rice", "Fry chicken"],
        "prep_minutes": 25,
        "servings": 2,
        "ingredients": [
            {"ingredient_id": chicken, "quantity": 200, "role": "primary"},
            {"ingredient_id": rice, "quantity": 300, "role": "supporting"},
        ],
    }


def test_create_recipe_returns_ingredients_and_derived_macros(client, stir_fry):
    """POST /recipes returns 201 with named ingredient lines and macros derived from them."""
    response = client.post("/recipes", json=stir_fry)

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Chicken stir fry"
    assert body["instructions"] == ["Cook rice", "Fry chicken"]
    assert [(i["name"], i["quantity"], i["role"]) for i in body["ingredients"]] == [
        ("Chicken", 200, "primary"),
        ("Rice", 300, "supporting"),
    ]
    assert body["macros"] == pytest.approx({
        "calories": 2 * 165 + 3 * 130,
        "protein": 2 * 31 + 3 * 2.7,
        "carbs": 3 * 28,
        "fat": 2 * 3.6 + 3 * 0.3,
    })


def test_supplied_macros_are_ignored(client, stir_fry):
    """Macros sent by the client never override the derived ones."""
    body = client.post(
        "/recipes", json={**stir_fry, "macros": {"calories": 1}}
    ).json()

    assert body["macros"]["calories"] == pytest.approx(2 * 165 + 3 * 130)


def test_get_recipe_by_id(client, stir_fry):
    """GET /recipes/{id} returns the same recipe the create call returned."""
    created = client.post("/recipes", json=stir_fry).json()

    response = client.get(f"/recipes/{created['id']}")

    assert response.status_code == 200
    assert response.json() == created


def test_unknown_recipe_returns_404(client):
    """GET /recipes/{id} for a recipe that does not exist returns 404."""
    response = client.get("/recipes/999")

    assert response.status_code == 404
    assert response.json() == {"detail": "Recipe 999 not found"}


def test_list_recipes_is_alphabetical(client, stir_fry):
    """GET /recipes returns every recipe sorted by name."""
    client.post("/recipes", json=stir_fry)
    client.post("/recipes", json={**stir_fry, "name": "Burrito bowl"})

    response = client.get("/recipes")

    assert response.status_code == 200
    assert [r["name"] for r in response.json()] == ["Burrito bowl", "Chicken stir fry"]


def test_unknown_ingredient_returns_404_and_stores_nothing(client, stir_fry):
    """A recipe referencing missing ingredients is rejected with their ids."""
    stir_fry["ingredients"].append({"ingredient_id": 999, "quantity": 10, "role": "optional"})

    response = client.post("/recipes", json=stir_fry)

    assert response.status_code == 404
    assert response.json() == {"detail": "Ingredients not found: [999]"}
    assert client.get("/recipes").json() == []


def test_invalid_recipes_are_rejected_with_422(client, stir_fry):
    """Invalid recipe input is rejected before anything is stored."""
    first = stir_fry["ingredients"][0]
    for bad in (
        {"ingredients": []},
        {"ingredients": [first, {**first, "quantity": 50}]},
        {"ingredients": [{**first, "quantity": 0}]},
        {"ingredients": [{**first, "role": "garnish"}]},
        {"servings": 0},
        {"servings": 1.5},
        {"prep_minutes": -1},
        {"name": " "},
    ):
        response = client.post("/recipes", json={**stir_fry, **bad})
        assert response.status_code == 422, bad

    assert client.get("/recipes").json() == []


def test_repeated_ingredient_error_explains_the_rule(client, stir_fry):
    """The 422 for a repeated ingredient carries the rule's message, not an empty object."""
    first = stir_fry["ingredients"][0]

    response = client.post("/recipes", json={**stir_fry, "ingredients": [first, first]})

    error = response.json()["detail"][0]
    assert error["loc"] == ["body", "ingredients"]
    assert error["ctx"] == {"error": "each ingredient may appear at most once in a recipe"}


def test_macros_per_serving_divides_by_servings(client, stir_fry):
    """macros_per_serving is the whole recipe's macros divided by its servings."""
    body = client.post("/recipes", json=stir_fry).json()

    assert body["macros_per_serving"] == pytest.approx(
        {name: value / 2 for name, value in body["macros"].items()}
    )


def test_duplicate_recipe_name_is_rejected_with_409(client, stir_fry):
    """Adding a recipe whose name already exists returns 409 and stores nothing new."""
    client.post("/recipes", json=stir_fry)

    response = client.post("/recipes", json=stir_fry)

    assert response.status_code == 409
    assert response.json() == {"detail": "Recipe 'Chicken stir fry' already exists"}
    assert len(client.get("/recipes").json()) == 1


def test_losing_a_same_name_race_is_rejected_with_409(app, client, stir_fry):
    """A recipe whose name another request commits after the duplicate check gets 409."""

    def other_request_commits_first(*_args):
        """Commit a recipe with the same name in another session, as a concurrent request would.

        Runs as this request flushes its insert: after its duplicate check found nothing.

        Args:
            *_args: The event's arguments; unused.
        """
        with app.state.session_factory() as other_session:
            other_session.add(Recipe(
                name=stir_fry["name"], instructions=["Cook"], prep_minutes=10, servings=1,
                recipe_ingredients=[RecipeIngredient(
                    ingredient_id=stir_fry["ingredients"][0]["ingredient_id"],
                    quantity=100,
                    role=IngredientRole.PRIMARY,
                )],
            ))
            other_session.commit()

    event.listen(app.state.session_factory, "before_flush", other_request_commits_first, once=True)
    response = client.post("/recipes", json=stir_fry)

    assert response.status_code == 409
    assert response.json() == {"detail": "Recipe 'Chicken stir fry' already exists"}
    assert [recipe["prep_minutes"] for recipe in client.get("/recipes").json()] == [10]


def test_listing_recipes_runs_a_fixed_number_of_queries(client, count_queries, stir_fry):
    """GET /recipes does not run extra queries per recipe or per ingredient (no N+1)."""
    client.post("/recipes", json=stir_fry)
    with count_queries() as few:
        client.get("/recipes")

    for n in range(3):
        extra = add_ingredient(client, f"Extra {n}", 100, 10, 10, 1)
        client.post("/recipes", json={**stir_fry, "name": f"Recipe {n}", "ingredients": [
            *stir_fry["ingredients"], {"ingredient_id": extra, "quantity": 50, "role": "optional"},
        ]})
    with count_queries() as many:
        assert len(client.get("/recipes").json()) == 4

    assert many[0] == few[0]
