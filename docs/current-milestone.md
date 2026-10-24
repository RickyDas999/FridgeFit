# FridgeFit — Current Milestone

Snapshot of the repository's actual state. Update this file whenever a slice or milestone lands.
If it disagrees with the code, the code is correct and this file is stale.

Last updated: 2026-10-24

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
4. **Minimal Demo Frontend**: a React + TypeScript + Vite dashboard over the V1 API with a
   reproducible demo seed: ranked recommendations with their reasons, meal logging with
   idempotency keys and shortfall override, meal rating, a deliberate visual design, and a
   README demo walkthrough. Added local CORS and a frontend CI job; no API contract changed.

**Advisory AI pull-request review is integrated into CI** (see CI below). This was pipeline work,
not a feature milestone.

5. **Production Reliability**: one checkpoint, concurrent idempotency hardening. Previously, two
   requests with the same new `Idempotency-Key` could both miss the key lookup and both attempt
   confirmation; the unique constraint on `MealLog.idempotency_key` rejected the later commit,
   which surfaced as a 500. Now the losing request rolls back its failed transaction, looks the
   key up again, and returns the winner's MealLog as an ordinary replay (200). A loser that
   instead loads stock after the winner committed, and so fails on a shortfall, also looks the
   key up again before returning 409. Exactly one MealLog, one set of MealLogIngredient rows, and
   one inventory decrement exist for the key. Regression tests:
   `test_losing_a_same_key_race_returns_the_winners_meal`,
   `test_shortfall_caused_by_a_same_key_winner_returns_the_winners_meal`, and
   `test_unrelated_integrity_error_is_not_mistaken_for_a_replay` in `tests/test_api_meals.py`.

**Active milestone: 6 — Deployment + Durable Persistence.** Moves FridgeFit from a local SQLite
demo to a deployed system (Render Static Site → Render FastAPI web service → Render PostgreSQL)
while keeping SQLite for local development. The target architecture is recorded in
`docs/architecture.md` › Environments and Deployment. Slices land one at a time, each only after
the developer authorizes it; nothing below is implemented unless marked so.

| Slice | Scope | Status |
|---|---|---|
| 0 | Milestone activation and architecture documentation | Implemented |
| 1 | Environment-based database configuration (`DATABASE_URL`, SQLite fallback) | Implemented |
| 2 | Alembic migration foundation: baseline migration, deliberate startup behavior | Implemented |
| 3 | PostgreSQL driver and compatibility, verified in CI against real PostgreSQL | Implemented |
| 4 | Safe demo data: separate dataset insertion from the destructive local reset | Implemented |
| 5 | Production backend configuration: env-driven CORS, port binding, Render build/start | Implemented |
| 6 | Deploy backend + PostgreSQL and validate operations (developer-owned Render steps) | Not started |
| 7 | Production frontend configuration + deployment, full browser workflow | Not started |
| 8 | Deployment reliability + documentation closeout | Not started |

The milestone is complete only when the deployed browser → API → PostgreSQL workflow, including
meal-confirmation writes and idempotent replay, has actually been exercised.

Found while planning, for the slices named:

- Two confirmations with different keys can still both read the same stock and overwrite each
  other's decrement (lost update). Acceptable under the single-user assumption; revisit if that
  changes. (The same-key race tests pass on PostgreSQL.)
- Slice 6: apply `render.yaml` as a Blueprint (it creates PostgreSQL 16, matching CI, and the
  web service). Render's free database is deleted 30 days after creation (14-day grace to
  upgrade) and has no backups; note the creation date. Rebuilding is: new database, deploy
  (migrations run on start), `scripts/seed_demo.py --insert-only`. Confirm Render accepts
  `PYTHON_VERSION: "3.12"` (a full patch version may be required).
- Slice 6 → 7: until `FRONTEND_ORIGIN` is set, the deployed API falls back to the local Vite
  origins. Set it to the static site's exact origin once that URL exists.

## Known Follow-ups

Deliberate shortcuts and cleanup, recorded so they are not lost:

- A `fridgefit.db` created before Alembic has no migration version, so `alembic upgrade head`
  fails on it ("table already exists"); re-running the seed rebuilds it at the latest migration.
- The migration parity test (`compare_metadata`) catches added/removed columns, tables, and unique
  constraints, but not changed check-constraint expressions: Alembic does not compare those.
- Demo data loaded once with `--insert-only` (the deployed database) ages: dates are relative to
  the insert, so expiries pass and "today's" meal moves into the past. Refreshing it is a
  deliberate manual step (empty the database, then `--insert-only` again); no code path wipes a
  non-SQLite database.
- Authentication is deferred: once deployed (Milestone 6), the demo is public and anyone with the
  URL can read and write its data.
- The frontend has no automated tests; CI only type-checks and builds it. Behavior is verified
  by hand (README demo walkthrough).
- Every write (logging or rating a meal) refetches all four dashboard sections; fine for one
  user, narrower refreshes if it ever matters.
- "Today" is the server's date (endpoints default `as_of` to it); a server in another timezone
  would shift the day boundary.

## Implemented

### Persistence (`app/persistence/`)

Models: Ingredient, InventoryBatch, Recipe, RecipeIngredient, MealLog, MealLogIngredient,
NutritionGoal, MealFeedback.

`database.py`: `get_database_url()` returns the `DATABASE_URL` environment variable, read when
called, or `sqlite:///fridgefit.db` when it is unset or empty. A PostgreSQL URL without a driver
(`postgres://` or `postgresql://`, as hosts hand out) is rewritten to `postgresql+psycopg://`, so
the driver is psycopg 3 whatever SQLAlchemy version is installed. The foreign-key `PRAGMA` hook
runs only on SQLite connections. `Base.metadata` has a naming convention for primary keys, foreign
keys, unique constraints, and indexes.

Migrations (`alembic/`, `alembic.ini`): one revision, `d22b106d0d3b` (baseline schema: all eight
tables, autogenerated and then reviewed against the models). `env.py` migrates the database from
`get_database_url()` and uses SQLite batch mode; offline (`--sql`) mode is not supported. Apply
with `.venv/bin/alembic upgrade head`. Alembic is a runtime dependency, since deployment runs it.

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
| `enjoyment.py` | `assess_recipe_enjoyment(recipe, rating_summaries)`, `RatingSummary(average, count)` |
| `recent_frequency.py` | `recent_window_start(as_of)`, `group_meal_dates_by_recipe(meal_logs, as_of)`, `assess_recent_frequency(recipe, meal_dates_by_recipe, last_eaten_by_recipe, as_of)` |
| `recommendations.py` | `recommend_recipes(recipes, batches, as_of, remaining_macros, rating_summaries, recent_meal_logs, last_eaten_by_recipe)`, `combine_scores(scores)` |

- Recommendations describe cooking one serving: availability compares stock with each
  ingredient's per-serving quantity (reported as `IngredientAvailability.quantity_per_serving`),
  and macro fit scores one serving's macros.
- `recommend_recipes` drops ineligible recipes, scores the rest, and returns `Recommendation`s
  (recipe, combined score, availability, expiry-urgency, macro-fit, enjoyment, and recent-frequency
  details) highest score first.
- `remaining_macros` is required but may be None (no nutrition goal in effect yet). Macro fit is
  then skipped, `Recommendation.macro_fit` is None, and `combine_scores` rescales the remaining
  default weights to sum to 1. This is the only case where weights are rescaled.
- `rating_summaries` is required: `{recipe_id: RatingSummary(average, count)}` for recipes with
  ratings (manual meals excluded); pass an empty mapping when nothing has been rated. Enjoyment
  is always scored (0.5 when unrated), so with a nutrition goal all four weights apply
  unscaled.
- `recent_meal_logs` (meals from `recent_window_start(as_of)` through `as_of`) and
  `last_eaten_by_recipe` (each recipe's latest meal date from full history, e.g. a
  `MAX ... GROUP BY` query) are required and used only for `Recommendation.recent_frequency`;
  they never affect the score. Full meal history is not needed. Dates after `as_of` in either
  input are ignored.
- Each `Recommendation.expiry_urgency.expired_batches` lists batches past their use-by date, as
  warnings.
- `Recommendation.expiry_urgency.ingredients` gives each recipe ingredient's earliest unexpired
  use-by date among batches with stock (the date its urgency comes from; None when undated or
  only expired) and `expiring_soon` (within 2 days). The score itself is unchanged by this.

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
  - rating summaries whose average is outside 1-5 or that summarize no ratings (each stored
    rating is a whole number 1-5 by database check constraint).
- Persistence never imports from `app/domain/`.

### HTTP API (`app/api/`)

- `app/api/main.py`: `create_app(database_url=None)` builds the app; without a URL it uses
  `get_database_url()`, so the module-level `app` uses `DATABASE_URL` or the local SQLite file.
  Run locally with `.venv/bin/uvicorn app.api.main:app --reload`.
- Startup (lifespan) does not create tables; the schema comes from migrations. Shutdown disposes
  the engine.
- CORS (`CORSMiddleware`) allows the origins from `get_frontend_origins()`: exactly
  `FRONTEND_ORIGIN` when that environment variable is set (trailing `/` dropped; `*` is refused
  with a `ValueError` at startup), otherwise the local Vite origins in `LOCAL_FRONTEND_ORIGINS`
  (`http://localhost:5173`, `http://127.0.0.1:5173`). Methods `GET` and `POST`, request headers
  `Content-Type` and `Idempotency-Key`; no credentials. Other origins get no CORS headers
  (preflight → 400).
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
    `is_missing`), expiry urgency (with expired batches as warnings, and per ingredient
    `use_by_date` and `expiring_soon`), macro fit (null without a goal), enjoyment, and recent
    frequency.
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

### Query loading

- List endpoints eager-load the relationships they read with `selectinload`, so their query
  count is fixed however much data exists (no N+1): `GET /recipes` (lines → ingredient, 3
  queries), `get_recommendations` (recipe lines → ingredient; 9 in total),
  and `GET /meal-logs` (lines → ingredient, and the rating; 4).
- Single-item paths (`GET /recipes/{id}`, `POST /recipes`, confirm, feedback) still load lazily;
  their cost is bounded by one recipe or meal.
- A `count_queries` fixture (`tests/conftest.py`) counts executed SQL; each list endpoint has a
  test asserting its count does not grow when more rows are added.

### Application workflows (`app/application/`)

- `nutrition.py`: `get_nutrition_state(session, as_of)` loads goals and only that day's meals
  (filtered by `consumed_at` in the query) and returns the applicable goal and remaining macros
  (`select_applicable_goal`, `calculate_remaining_macros`). Used by `GET /nutrition-state`;
  read-only.
- `recommendations.py`: `get_recommendations(session, as_of)` loads recipes, batches with stock,
  remaining macros (via `get_nutrition_state`), each recipe's rating average and count
  (`AVG`/`COUNT ... GROUP BY recipe_id`, manual meals excluded, `AVG` cast to float so
  PostgreSQL's NUMERIC does not arrive as `Decimal`), the recent-frequency window's meals, and
  each recipe's last-eaten date (`MAX(consumed_at) ... GROUP BY recipe_id`), then calls
  `recommend_recipes`. Neither meal history nor ratings are loaded in full. Read-only.
- `meals.py`: `confirm_recipe_meal(session, recipe, ...)` returns the existing MealLog (with
  `created=False`) when the idempotency key was already confirmed; otherwise calls
  `confirm_meal`, which writes the key in its own atomic commit. If that commit fails with an
  `IntegrityError` while a key was given, it rolls the session back and looks the key up again:
  found means another request committed it first, so that MealLog is returned as a replay
  (`created=False`); not found means an unrelated violation, which is re-raised. A shortfall with
  a key gets the same second lookup (no rollback needed: nothing was written), so a shortfall
  caused by a same-key winner replays instead of returning 409.

### Deployment configuration (`render.yaml`)

Prepared, not yet applied (Slice 6 applies it). A Render Blueprint declaring:

- `fridgefit-api`: free Python web service. Build `pip install .` (runtime dependencies only).
  Start `alembic upgrade head && uvicorn app.api.main:app --host 0.0.0.0 --port $PORT`: the free
  plan has no pre-deploy command, so migrations run before every start, a no-op when current. On
  a paid plan, `alembic upgrade head` would move to a pre-deploy command. Health check
  `/health`. Environment: `PYTHON_VERSION` 3.12, `DATABASE_URL` linked from the database,
  `FRONTEND_ORIGIN` entered in the dashboard (`sync: false`).
- `fridgefit-db`: free PostgreSQL 16, database and user `fridgefit`.
- Both in the `virginia` region (US East), so the API reaches the database over Render's private
  network. A database's region is fixed when it is created.
- No secrets in the file. Rehearsed locally (clean virtualenv, the exact build and start
  commands, an empty PostgreSQL database and a plain `postgresql://` URL): the first start
  migrated, `/health` and CORS answered as configured, and a restart ran no migration and kept
  the data.

### Demo seed (`scripts/seed_demo.py`)

- Run from the repository root against the app's database (`get_database_url()`:
  `DATABASE_URL` or `fridgefit.db`). The dataset is inserted through the ORM (not the HTTP API)
  by `insert_demo_data(session, now)`, shared by two modes:
  - Default, `.venv/bin/python scripts/seed_demo.py`: local reset. Drops every table, including
    Alembic's version table, rebuilds them with `alembic upgrade head`, then inserts, so each run
    gives the same known state. Refuses (exit with a message, nothing touched) when the database
    is not SQLite.
  - `--insert-only`: for any database, including deployed PostgreSQL. Never drops or alters
    anything; inserts only when the database is at the latest migration and every table is
    empty, and otherwise refuses with the reason (nothing written).
- Arguments are parsed with `argparse`, so an unknown or mistyped flag exits before either mode
  runs instead of falling through to the reset.
- All dates are relative to when the data is inserted: 13 ingredients; 14 batches (chicken due
  tomorrow and in 5 days, spinach due today plus an expired spinach batch, undated staples, no
  salmon, too few black beans); 6 recipes (fully available, one missing a PRIMARY ingredient,
  one partly available); a goal effective 30 days ago; 7 past meals with macros from
  `calculate_recipe_macros` (the rice bowl twice in the last 7 days; today's breakfast
  unrated, the rest rated 2–5).
- Past meals do not consume current inventory.

### Frontend (`frontend/`)

- React 19 + TypeScript + Vite 8 (template `react-ts`, ESLint/oxlint and demo assets removed).
  Runtime dependencies: `react`, `react-dom`, and `@fontsource-variable/atkinson-hyperlegible-next`
  (the self-hosted typeface, imported in `src/main.tsx`).
- `src/api.ts` is the API boundary: `API_BASE_URL` from `VITE_API_BASE_URL`, defaulting to
  `http://127.0.0.1:8000`; TypeScript types mirroring the response schemas; `checkHealth()`
  (connected, unreachable — network or CORS failure — or error response); and read fetchers
  `getNutritionState`, `getInventory`, `getRecommendations`, `getTodaysMeals`, `getRecipe`. The
  dashboard fetchers omit date parameters, so the server's "today" applies. `confirmMeal()`
  posts to `/recipes/{id}/confirm` with a caller-supplied `Idempotency-Key` and returns
  `logged` (201, or 200 when replayed) or `shortfall` (409); other errors become readable
  messages. `rateMeal()` posts to `/meal-logs/{id}/feedback` and returns `rated` or
  `already_rated` (409).
- `src/useResource.ts`: the `useResource` hook (loading/error/ready for one request, ignoring
  late responses). A `reloadToken` argument refetches while keeping the current data on
  screen. `src/format.ts`: display formatting (units, 0–100 scores, times, and
  calendar dates built from their parts to avoid a UTC off-by-one-day).
- `src/App.tsx`: header with the backend status ("Connected" or "Offline", with "Try again"
  when offline), then the dashboard.
- `src/Dashboard.tsx`: the dashboard (Slice 2). Four sections, each loading on its own with
  its own loading and error state: "What to make" (ranked recommendations with score,
  availability %, missing ingredients, expired-batch count, times eaten this week), "Today"
  (calories and macros left of the goal, "over" when negative, a message when no goal
  applies), "Eaten today" (time, name, calories, rating), and "In the fridge" (inventory with
  units). It only formats API values; no domain calculation happens in the frontend.
- `src/RecommendationDetail.tsx` (Slice 3): clicking a recommendation expands its detail
  (one open at a time). It shows the four component scores (macro fit "No goal" when null) but
  not the backend's weights; a need/have table per serving with "None" or "N% of need" flags
  (from `is_missing` and `fraction_available`) and a "Use by" column ("Today", "Tomorrow",
  or a date; amber when the API flags `expiring_soon`; "–" when none); expired batches by name
  and use-by date; a line explaining that expiry urgency ignores already-expired food;
  enjoyment and recent frequency; and recipe basics — prep time, servings, per-serving macros,
  instructions — from `GET /recipes/{id}`, loaded when the detail opens (which also supplies
  ingredient units).
- `src/LogMeal.tsx` (Slice 4): "I ate this" in a recommendation's detail opens a servings form
  (default 1, step 0.5, any amount above 0) and "Log meal". Server time and recipe name are
  used. Each submission keeps its Idempotency-Key (`crypto.randomUUID()`) until it succeeds, so
  a retry after a network failure cannot log twice; changing servings starts new keys. The
  button is disabled while a request is in flight. A shortfall lists what is short (need/have)
  and offers "Log anyway with what I have" (`allow_shortfall: true`, its own key). On success
  the dashboard shows "Logged …" and refetches all four panels; the open detail stays open.
- `src/RateMeal.tsx` (Slice 5): each unrated meal in "Eaten today" shows 1–5 buttons; rated
  meals show "Rated N/5". No idempotency key: the backend stores one rating per meal, so a
  repeat is rejected (409). Buttons are disabled while sending. On success or "already rated"
  the dashboard shows a notice and refetches, so the stored rating and the recipe's enjoyment
  score update.
- Design pass (Slice 6): `src/index.css` is one token system (light and dark) following
  `architecture.md` § Visual design. Layout: the ranked list on a white "shelf" with the top
  pick set large; a sidebar with Today (calories left as the one large figure, meters for
  calories and macros that turn amber below 15% left and red when over — display thresholds
  only), Eaten today, and In the fridge, divided by rules. The detail shows need/have in a
  table.
- Offline handling: `api.ts` throws `BackendUnreachable` when no response arrives, and
  `useResource` marks that error `offline`. Sections and the recipe detail then show "Waiting for
  the API…" while the header banner explains once how to start it; real API errors still show in
  red. "Try again" re-checks `/health` and, when the API is back, remounts the dashboard
  (`key`) so every section refetches.
- `npm run dev` serves it on `http://localhost:5173`; `npm run build` type-checks (`tsc -b`) and
  builds.

### Tests

264 tests across `tests/test_models.py`, `tests/test_database.py`, `tests/test_migrations.py`,
`tests/test_seed_demo.py`, `tests/test_ai_review.py`, one test module per domain
module, and `tests/test_api.py` plus one `tests/test_api_<resource>.py` per route module. Run
with:

```bash
.venv/bin/ruff check .
.venv/bin/python -m pytest tests/ -v
```

- Database tests get an empty database from the `empty_database_url` fixture (`conftest.py`): a
  new SQLite file per test, or, when `TEST_DATABASE_URL` is set, that PostgreSQL database with
  its `public` schema dropped and recreated before every test. The `session` and `app` fixtures
  build tables with `create_all`; the migration tests run Alembic on the same database.
- Against PostgreSQL (all 258 pass on PostgreSQL 15 locally and run on 16 in CI):

  ```bash
  TEST_DATABASE_URL=postgresql+psycopg://USER@localhost/fridgefit_test \
    .venv/bin/python -m pytest tests/ -v
  ```

  The database must exist and is wiped by every test; never point it at real data.
- Tests that check SQLite-specific or local-only behavior (seed, URL selection, startup) use
  their own SQLite URLs either way.

### CI

- `.github/workflows/ci.yml` runs `ruff check .` and `pytest` on Python 3.11 and 3.12 for every
  pull request and every push to `main`, plus a separate "Frontend build" job (Node 22) that
  runs `npm ci` and `npm run build` in `frontend/` from the committed lockfile.
- A "Test on PostgreSQL 16" job runs the full pytest suite (Python 3.12) with `TEST_DATABASE_URL`
  pointing at a throwaway `postgres:16` service container, so models, migrations, and API
  behavior are exercised on real PostgreSQL. Its credentials exist only inside that container.
- Ruff is pinned (`ruff==0.16.10`) and configured in `pyproject.toml`.
- `main` is protected: changes merge only through a pull request with both CI checks passing; no
  approval is required, and the admin can bypass in an emergency. The PostgreSQL job is not a
  required check unless the developer adds it to branch protection.
- `.github/workflows/ai-review.yml` runs an advisory semantic review when the developer adds the
  `ai-review` label to a pull request (or runs the workflow manually). It never runs on ordinary
  pushes.
  - `scripts/ai_review.py` gathers a bounded bundle deterministically: PR title, description,
    changed-file list, the diff of human-authored files, unchanged test files for changed
    modules, and relevant doc sections. Generated files (including `frontend/package-lock.json`)
    are excluded, and the bundle has a hard size ceiling.
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

- Frontend data-entry screens: ingredients, groceries, recipes, nutrition goals, and manual
  inventory correction (data comes from the seed script or the API)
- Manual macro-only meal creation, in the API or the frontend
- Authentication and users
- Nutrition-data API integration
- Runtime Claude meal generation
- Ranking weights configurable per recommendation request (the defaults are fixed in
  `DEFAULT_WEIGHTS`)
- Manual inventory correction
- Recipe editing and deletion
- Alembic migrations, PostgreSQL support, and deployment (Milestone 6, in progress; see Status)
- Docker (not planned unless deployment needs it)
- Redis, queues, and microservices
