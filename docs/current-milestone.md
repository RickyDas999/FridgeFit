# FridgeFit — Current Milestone

Snapshot of the repository's actual state. Update this file whenever a slice or milestone lands.
If it disagrees with the code, the code is correct and this file is stale.

Last updated: 2026-10-07

---

## Status

**Completed: Core Deterministic Domain Logic.** All five planned slices are implemented and tested.

**Active milestone: Recommendations.** Governing rules are in the Recommendations section of
`docs/domain-rules.md`. Every slice is a pure function in `app/domain/` and adds to a working
ranker, so each slice ends with runnable recommendations.

| # | Slice | Status |
|---|---|---|
| 1 | Availability, eligibility, and a weighted-sum ranker (`availability.py`, `recommendations.py`) | Done |
| — | Input validation (`app/errors.py`, `app/domain/validation.py`, save-time recipe check) | Done |
| 2 | Freshness score and expired-batch warnings (`freshness.py`) | Done |
| 3 | Macro fit score (`macro_fit.py`) | Done |
| 4 | Enjoyment score (`enjoyment.py`) | Implemented, not yet committed |
| 5 | Recent frequency shown informationally | Not started |

**After this milestone:** the developer adds Codex to the CI pipeline as an additional review
layer. Do not start another milestone when slice 5 lands; stop at that point.

Until a component's slice lands, `combine_scores` leaves it out and rescales the remaining default
weights to sum to 1.

## Implemented

### Persistence (`app/persistence/`)

Models: Ingredient, InventoryBatch, Recipe, RecipeIngredient, MealLog, MealLogIngredient,
NutritionGoal, MealFeedback.

Schema details beyond the core domain rules:

- `Recipe.prep_minutes` and `Recipe.servings` (both required).
- `MealLog.name` (required).
- `MealLog.recipe_id`: nullable foreign key to the Recipe the meal came from.
- `MealLog.idempotency_key`: nullable, unique UUID. Present in the schema but not yet used by any
  domain logic.
- `MealFeedback`: one 1–5 rating per MealLog, enforced by a unique foreign key.
- `Recipe.servings` must be positive, enforced by a database check constraint.
- A SQLAlchemy `before_flush` hook in `models.py` rejects saving a Recipe with no ingredients: a
  new empty recipe, emptying a saved recipe, or deleting its last ingredient.

### Domain logic (`app/domain/`)

| Slice | Module | Entry point |
|---|---|---|
| 1. Recipe macro calculation | `recipe_macros.py` | `calculate_recipe_macros(recipe, quantity_overrides=None)` |
| 2. Current nutrition state | `nutrition_state.py` | `select_applicable_goal`, `calculate_remaining_macros` |
| 3. Inventory aggregation | `inventory_aggregation.py` | `aggregate_inventory_by_ingredient(batches)` |
| 4. FEFO consumption | `fefo_consumption.py` | `plan_fefo_consumption(batches, quantity_needed)` |
| 5. Meal confirmation | `meal_confirmation.py` | `confirm_meal(session, recipe, *, consumed_at, name=None, allow_shortfall=False)` |

Implementation behavior worth knowing:

- **Recipe macros** accept optional per-ingredient quantity overrides keyed by
  `RecipeIngredient.id`. With no overrides, the recipe's stated quantities are used.
- **Remaining macros** subtract only MealLogs whose `consumed_at` falls on the same calendar day as
  the requested date. A `ValueError` is raised if no goal is effective yet.
- **Inventory aggregation** sums `quantity_remaining` per ingredient.
- **FEFO planning** is read-only. It returns a plan, and returns a partial plan (not an error) when
  inventory is insufficient.
- **Meal confirmation** plans every ingredient before mutating anything, then commits the MealLog,
  MealLogIngredients, and batch decrements in one transaction.
  - By default, any shortfall raises `InsufficientInventoryError` and nothing is written.
  - With `allow_shortfall=True`, the meal is confirmed anyway because kitchen inventory is an
    estimate. Only available inventory is consumed and batches never go negative. Emptied batches
    get `depleted_at`. `MealLogIngredient.quantity` and the MealLog macros reflect the amount
    actually consumed, not the recipe's stated amount. An ingredient with nothing available gets no
    MealLogIngredient row.
  - Ingredient roles (PRIMARY/SUPPORTING/OPTIONAL) do not affect confirmation; every ingredient is
    consumed.

### Recommendations (`app/domain/`)

| Module | Entry point |
|---|---|
| `availability.py` | `assess_recipe_availability(recipe, inventory_totals)` |
| `freshness.py` | `assess_recipe_freshness(recipe, batches_by_ingredient, as_of)` |
| `macro_fit.py` | `assess_macro_fit(recipe, remaining)` |
| `enjoyment.py` | `group_ratings_by_recipe(meal_feedback)`, `assess_recipe_enjoyment(recipe, ratings_by_recipe)` |
| `recommendations.py` | `recommend_recipes(recipes, batches, as_of, remaining_macros, meal_feedback)`, `combine_scores(scores)` |

- `recommend_recipes` drops ineligible recipes, scores the rest, and returns `Recommendation`s
  (recipe, combined score, availability, freshness, macro-fit, and enjoyment details) highest
  score first.
- `remaining_macros` is required but may be None (no nutrition goal in effect yet). Macro fit is
  then skipped and `Recommendation.macro_fit` is None.
- `meal_feedback` is required; pass an empty sequence when nothing has been rated. Enjoyment is
  always scored (0.5 when unrated), so with a nutrition goal all four weights apply unscaled.
- Each `Recommendation.freshness.expired_batches` lists batches past their use-by date, as
  warnings.

### Input validation

- `app/errors.py` defines `InvalidInputError(ValueError)`, raised by all input validation, in
  both layers.
- `app/domain/validation.py` holds the domain input validators; each domain function calls the
  ones it needs at its top. They reject:
  - a recipe with no ingredients or non-positive servings;
  - non-positive recipe-ingredient quantities, nutrition base quantities, and FEFO
    `quantity_needed`; negative quantity overrides;
  - quantity overrides keyed by a RecipeIngredient that is not part of the recipe;
  - FEFO batch lists that mix ingredients;
  - a `datetime` passed as `as_of` (nutrition state, freshness, recommendations);
  - ratings that are not whole numbers from 1 to 5.
- Persistence never imports from `app/domain/`.

### Tests

142 tests across `tests/test_models.py` and one test module per domain module. Run with:

```bash
.venv/bin/ruff check .
.venv/bin/python -m pytest tests/ -v
```

### CI

- `.github/workflows/ci.yml` runs `ruff check .` and `pytest` on Python 3.11 and 3.12 for every
  pull request and every push to `main`.
- Ruff is pinned (`ruff==0.16.10`) and configured in `pyproject.toml`.
- `main` is protected: changes merge only through a pull request with both CI checks passing; no
  approval is required, and the admin can bypass in an emergency.

## Intentionally Unimplemented

- FastAPI / API layer
- Recent-frequency display in recommendations (slice 5)
- Nutrition-data API integration
- Claude API integration
- Use of `MealLog.idempotency_key` in meal confirmation
- Grocery addition and manual inventory correction operations
- Alembic migrations
- Docker
- Agent (Codex) review in CI
