# FridgeFit — Current Milestone

Snapshot of the repository's actual state. Update this file whenever a slice or milestone lands.
If it disagrees with the code, the code is correct and this file is stale.

Last updated: 2026-10-11

---

## Status

**Completed milestones:**

1. **Core Deterministic Domain Logic**: recipe macros, nutrition state, inventory aggregation,
   FEFO consumption, and atomic meal confirmation.
2. **Recommendations**: availability, freshness, macro fit, and enjoyment scoring combined into a
   weighted ranking, plus informational recent frequency. Includes the input-validation slice and
   CI setup completed during the milestone.
3. **V1 HTTP API + Minimal Application Orchestration**: a FastAPI app exposing the domain logic
   through 14 endpoints (ingredients, inventory intake, recipes, nutrition goals and state,
   recommendations, idempotent meal confirmation, meal history, and feedback), with thin
   application workflows where persistence and domain logic meet. Grew the suite from 163 to
   231 tests.

**Advisory AI pull-request review is integrated into CI** (see CI below). This was pipeline work,
not a feature milestone.

**No feature milestone is active.** The next one has not been chosen. Do not start new feature
work until the developer approves the next milestone and its scope.

## Known Follow-ups

Deliberate shortcuts and cleanup, recorded so they are not lost:

- `app/domain/freshness.py` is a stale, unused copy left over from the rename to
  `expiry_urgency.py`. Remove it in a separate change.
- `get_recommendations` loads every MealFeedback row to average ratings; compute per-recipe
  averages in SQL as history grows.
- Recipes, their ingredients, and ratings' meals are lazy-loaded (N+1 queries) in
  `GET /recipes` and recommendations; add `selectinload` if it gets slow.
- Two concurrent confirmations with the same new idempotency key are not handled: the unique
  constraint rejects the second (a 500), so nothing is logged twice.
- New database constraints (e.g. unique recipe names) reach an existing `fridgefit.db` only if it
  is recreated, because startup's `create_all` never alters tables and Alembic is deferred.

## Implemented

### Persistence (`app/persistence/`)

Models: Ingredient, InventoryBatch, Recipe, RecipeIngredient, MealLog, MealLogIngredient,
NutritionGoal, MealFeedback.

Schema details beyond the core domain rules:

- `Recipe.prep_minutes` and `Recipe.servings` (both required).
- `MealLog.name` (required).
- `MealLog.recipe_id`: nullable foreign key to the Recipe the meal came from.
- `MealLog.idempotency_key`: nullable, unique UUID, written by `confirm_meal` when given.
- `MealFeedback`: one 1–5 rating per MealLog, enforced by a unique foreign key. `MealLog.feedback`
  is the one-to-one relationship back to it (None until rated).
- `Recipe.servings` must be positive, enforced by a database check constraint.
- `Recipe.name` is unique, enforced by a database unique constraint.
- A SQLAlchemy `before_flush` hook in `models.py` rejects saving a Recipe with no ingredients: a
  new empty recipe, emptying a saved recipe, or deleting its last ingredient.

### Core domain logic (`app/domain/`)

| Area | Module | Entry point |
|---|---|---|
| Recipe macro calculation | `recipe_macros.py` | `calculate_recipe_macros(recipe, quantity_overrides=None)` |
| Current nutrition state | `nutrition_state.py` | `select_applicable_goal`, `calculate_remaining_macros` |
| Inventory aggregation | `inventory_aggregation.py` | `aggregate_inventory_by_ingredient(batches)` |
| FEFO consumption | `fefo_consumption.py` | `plan_fefo_consumption(batches, quantity_needed)` |
| Meal confirmation | `meal_confirmation.py` | `confirm_meal(session, recipe, *, servings, consumed_at, name=None, allow_shortfall=False, idempotency_key=None)` |

Implementation behavior worth knowing:

- **Recipe macros** accept optional per-ingredient quantity overrides keyed by
  `RecipeIngredient.id`. With no overrides, the recipe's stated quantities are used.
- **Remaining macros** subtract only MealLogs whose `consumed_at` falls on the same calendar day as
  the requested date. A `ValueError` is raised if no goal is effective yet.
- **Inventory aggregation** sums `quantity_remaining` per ingredient.
- **FEFO planning** is read-only. It returns a plan, and returns a partial plan (not an error) when
  inventory is insufficient.
- **Meal confirmation** scales every ingredient to the required `servings` (cook only what is
  eaten), plans every ingredient before mutating anything, then commits the MealLog,
  MealLogIngredients, and batch decrements in one transaction.
  - By default, any shortfall raises `InsufficientInventoryError` and nothing is written.
  - With `allow_shortfall=True`, the meal is confirmed anyway because kitchen inventory is an
    estimate. Only available inventory is consumed and batches never go negative. Emptied batches
    get `depleted_at`. `MealLogIngredient.quantity` and the MealLog macros reflect the amount
    actually consumed, not the scaled recipe amount. An ingredient with nothing available gets no
    MealLogIngredient row.
  - Ingredient roles (PRIMARY/SUPPORTING/OPTIONAL) do not affect confirmation; every ingredient is
    consumed.
  - An optional `idempotency_key` is stored on the MealLog in the same commit. `confirm_meal`
    does not check for an existing key; that lookup belongs to the caller. A rejected
    confirmation writes nothing, so its key stays unused.

### Recommendations (`app/domain/`)

| Module | Entry point |
|---|---|
| `availability.py` | `assess_recipe_availability(recipe, inventory_totals)` |
| `expiry_urgency.py` | `assess_recipe_expiry_urgency(recipe, batches_by_ingredient, as_of)` |
| `macro_fit.py` | `assess_macro_fit(recipe, remaining)` |
| `enjoyment.py` | `group_ratings_by_recipe(meal_feedback)`, `assess_recipe_enjoyment(recipe, ratings_by_recipe)` |
| `recent_frequency.py` | `recent_window_start(as_of)`, `group_meal_dates_by_recipe(meal_logs, as_of)`, `assess_recent_frequency(recipe, meal_dates_by_recipe, last_eaten_by_recipe, as_of)` |
| `recommendations.py` | `recommend_recipes(recipes, batches, as_of, remaining_macros, meal_feedback, recent_meal_logs, last_eaten_by_recipe)`, `combine_scores(scores)` |

- Recommendations describe cooking one serving: availability compares stock with each
  ingredient's per-serving quantity (reported as `IngredientAvailability.quantity_per_serving`),
  and macro fit scores one serving's macros.
- `recommend_recipes` drops ineligible recipes, scores the rest, and returns `Recommendation`s
  (recipe, combined score, availability, expiry-urgency, macro-fit, enjoyment, and recent-frequency
  details) highest score first.
- `remaining_macros` is required but may be None (no nutrition goal in effect yet). Macro fit is
  then skipped, `Recommendation.macro_fit` is None, and `combine_scores` rescales the remaining
  default weights to sum to 1. This is the only case where weights are rescaled.
- `meal_feedback` is required; pass an empty sequence when nothing has been rated. Enjoyment is
  always scored (0.5 when unrated), so with a nutrition goal all four weights apply unscaled.
- `recent_meal_logs` (meals from `recent_window_start(as_of)` through `as_of`) and
  `last_eaten_by_recipe` (each recipe's latest meal date from full history, e.g. a
  `MAX ... GROUP BY` query) are required and used only for `Recommendation.recent_frequency`;
  they never affect the score. Full meal history is not needed. Dates after `as_of` in either
  input are ignored.
- Each `Recommendation.expiry_urgency.expired_batches` lists batches past their use-by date, as
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
  - a `datetime` passed as `as_of` (nutrition state, expiry urgency, recent frequency,
    recommendations);
  - ratings that are not whole numbers from 1 to 5.
- Persistence never imports from `app/domain/`.

### HTTP API (`app/api/`)

- `app/api/main.py`: `create_app(database_url)` builds the app; the module-level `app` uses the
  default SQLite file. Run locally with `.venv/bin/uvicorn app.api.main:app --reload`.
- Startup (lifespan) creates missing tables; shutdown disposes the engine.
- `app/api/session.py`: `get_session` gives each request its own Session, closed when the
  request ends; uncommitted changes are discarded. Routes receive it through `SessionDep`.
- One route module per resource (`ingredients.py`, `inventory.py`, `recipes.py`, `nutrition.py`,
  `recommendations.py`, `meals.py`), each holding its `APIRouter` and Pydantic schemas.
  Responses are built from ORM objects with `model_validate` (`from_attributes=True`), or field
  by field when they include derived or related values (recipe macros, recommendations, meal
  ingredients).
- Errors: `InvalidInputError` → 422 with `{"detail": <message>}`. Pydantic request validation →
  422 with a list of `loc`/`msg`/`type` errors; the rejected input is never echoed, because
  values such as `Infinity` cannot be encoded as JSON, and a custom validator's error in `ctx`
  is returned as its message text. Missing resources → 404; unknown paths → 404.
- Request schemas reject `Infinity`/`NaN` (`allow_inf_nan=False`), and request datetimes must be
  naive local time (timezone-aware values → 422), matching the stored datetimes and
  calendar-day logic.
- Endpoints (the complete V1 surface):
  - `GET /health`: also runs `SELECT 1` to confirm the database is reachable.
  - `POST /ingredients` (201): `nutrition_updated_at` is set to now by the server. A name that
    already exists (exact match) → 409.
  - `GET /ingredients`: all ingredients, by name.
  - `POST /inventory/batches` (201): `quantity` becomes both initial and remaining quantity;
    `purchased_at` defaults to now. Unknown `ingredient_id` → 404.
  - `GET /inventory`: total on hand per ingredient (`aggregate_inventory_by_ingredient`), by
    name; ingredients with nothing left are omitted.
  - `POST /recipes` (201): the recipe and its ingredient lines in one request and one commit.
    A name that already exists (exact match) → 409. At least one ingredient; a repeated
    `ingredient_id` → 422 (the domain rule is enforced here, not in the domain layer or
    database). Unknown ingredients → 404 listing their ids. Client-supplied macros are ignored.
  - `GET /recipes` (by name) and `GET /recipes/{recipe_id}` (missing → 404). Each recipe
    includes its ingredient lines (name, unit, quantity, role), `macros` for the whole recipe
    (derived with `calculate_recipe_macros`), and `macros_per_serving` (`macros / servings`).
  - `POST /nutrition-goals` (201): goals are append-only history; the effective date may be in
    the future. A second goal on the same effective date → 409.
  - `GET /nutrition-state?as_of=YYYY-MM-DD`: `as_of` defaults to today on the server's clock.
    Returns the applicable `goal` and `remaining` macros for that calendar day; both are null
    when no goal is effective yet (200, not an error).
  - `GET /recommendations?as_of=YYYY-MM-DD`: `as_of` defaults to today on the server's clock.
    Eligible recipes, highest score first, each with `score` and its components: availability
    (per ingredient: `quantity_per_serving`, `quantity_on_hand`, `fraction_available`,
    `is_missing`), expiry urgency (with expired batches as warnings), macro fit (null without a
    goal), enjoyment, and recent frequency.
  - `POST /recipes/{recipe_id}/confirm`: body `servings` (> 0, fractions allowed),
    `consumed_at` (naive local time, defaults to now), optional `name`, and `allow_shortfall`
    (default false). The idempotency key is the optional `Idempotency-Key` request header (a
    UUID; malformed → 422); an `idempotency_key` body field is ignored like any unknown field.
    201 with the new MealLog; 200 with the original MealLog when the key was already
    confirmed. The response's `idempotency_key` shows the stored key. Missing recipe → 404
    (checked before the key). Shortfall without the override → 409 with
    `{"detail": {"message", "shortfalls": [{ingredient_id, name, quantity_needed,
    quantity_available}]}}`; nothing is written.
  - `GET /meal-logs?consumed_on=YYYY-MM-DD`: that day's meals in `consumed_at` order, each with
    its macro snapshot, ingredient quantities, and `rating` (null until rated); `consumed_on`
    defaults to today. Meal-log responses from confirmation include `rating` too.
  - `POST /meal-logs/{meal_log_id}/feedback` (201): body `{"rating": 1-5}`, a strict whole
    number (`true`, `"4"`, and `4.0` → 422). Missing meal → 404; already rated → 409. Manual
    meals can be rated; their ratings count toward no recipe.

### Application workflows (`app/application/`)

- `nutrition.py`: `get_nutrition_state(session, as_of)` loads goals and only that day's meals
  (filtered by `consumed_at` in the query) and returns the applicable goal and remaining macros
  (`select_applicable_goal`, `calculate_remaining_macros`). Used by `GET /nutrition-state`;
  read-only.
- `recommendations.py`: `get_recommendations(session, as_of)` loads recipes, batches with stock,
  remaining macros (via `get_nutrition_state`), all meal feedback, the recent-frequency window's
  meals, and each recipe's last-eaten date (`MAX(consumed_at) ... GROUP BY recipe_id`), then
  calls `recommend_recipes`. Meal history is never loaded in full; meal feedback still is
  (marked `ponytail:`, to be aggregated in SQL later). Read-only.
- `meals.py`: `confirm_recipe_meal(session, recipe, ...)` returns the existing MealLog (with
  `created=False`) when the idempotency key was already confirmed; otherwise calls
  `confirm_meal`, which writes the key in its own atomic commit. Concurrent requests with the
  same new key are not handled: the unique constraint rejects the second one (a 500), so nothing
  is logged twice.

### Tests

234 tests across `tests/test_models.py`, `tests/test_ai_review.py`, one test module per domain
module, and `tests/test_api.py` plus one `tests/test_api_<resource>.py` per route module. Run
with:

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
- `.github/workflows/ai-review.yml` runs an advisory semantic review when the developer adds the
  `ai-review` label to a pull request (or runs the workflow manually). It never runs on ordinary
  pushes.
  - `scripts/ai_review.py` gathers a bounded bundle deterministically: PR title, description,
    changed-file list, the diff of human-authored files, unchanged test files for changed
    modules, and relevant doc sections. Generated files are excluded, and the bundle has a hard
    size ceiling.
  - It makes one Claude API review request with no tools, using `AGENTS.md` as the reviewer
    contract, and posts one structured PR comment with at most 3 findings. The response is
    validated locally against that structure (exactly one review block and a one-line summary).
  - A malformed or truncated response gets up to `MAX_REPAIR_ATTEMPTS` (2) sequential repair
    requests. Each carries only a `<repair_request>` with the validation problems and the
    rejected response, not the bundle; `AGENTS.md` § Repair Requests limits the model to keeping
    or dropping existing findings. A refusal is not retried. If no valid review results, a fixed
    `Status: ERROR` comment is posted. The comment footer shows the call count and total tokens.
  - It runs via `pull_request_target` from the trusted default branch and never checks out or
    executes PR-branch code; PR content is fetched with `gh` and treated as text only.
  - Generated-only, trivial documentation, and oversized PRs are skipped without a model call.
  - Advisory only: the workflow can read the repository and comment on the PR, but has no
    contents write and is not a required check.
  - Requires the `ANTHROPIC_API_KEY` repository secret; the model is set in the workflow.
- Trust model: Ruff and pytest are the deterministic source of truth; the Claude
  review is an independent semantic critic; the developer makes the final engineering judgment.

## Intentionally Unimplemented

- Frontend
- Authentication and users
- Nutrition-data API integration
- Runtime Claude meal generation
- Ranking weights configurable per recommendation request (the defaults are fixed in
  `DEFAULT_WEIGHTS`)
- Manual inventory correction
- Recipe editing and deletion
- Alembic migrations
- Docker and deployment
- Redis, queues, and microservices
