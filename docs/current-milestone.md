# FridgeFit — Current Milestone

Snapshot of the repository's actual state. Update this file whenever a slice or milestone lands.
If it disagrees with the code, the code is correct and this file is stale.

Last updated: 2026-10-25

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

6. **Deployment + Durable Persistence** (completed 2026-10-25): FridgeFit moved from a local
   SQLite demo to a deployed system (Render static site → Render FastAPI web service → Render
   PostgreSQL 16) while keeping SQLite for local development and fast tests. `DATABASE_URL`
   selects the database; Alembic migrations build and evolve every real database; the suite also
   runs on PostgreSQL in CI; the destructive demo reset cannot target production, and
   `--insert-only` loaded the deployed demo data; CORS allows exactly the deployed frontend's
   origin. Closed with deployment-reliability work: pooled connections are pre-pinged so a
   database restart fails no request, database-failure behavior was reproduced, and the README
   documents the deployment. The deployed browser → API → PostgreSQL workflow, including
   meal-confirmation writes and idempotent replay, was exercised. Architecture:
   `docs/architecture.md` › Environments and Deployment; operations: README › Deployment.

Milestone 6 slices:

| Slice | Scope | Status |
|---|---|---|
| 0 | Milestone activation and architecture documentation | Implemented |
| 1 | Environment-based database configuration (`DATABASE_URL`, SQLite fallback) | Implemented |
| 2 | Alembic migration foundation: baseline migration, deliberate startup behavior | Implemented |
| 3 | PostgreSQL driver and compatibility, verified in CI against real PostgreSQL | Implemented |
| 4 | Safe demo data: separate dataset insertion from the destructive local reset | Implemented |
| 5 | Production backend configuration: env-driven CORS, port binding, Render build/start | Implemented |
| 6 | Deploy backend + PostgreSQL and validate operations (developer-owned Render steps) | Implemented |
| 7 | Production frontend configuration + deployment, full browser workflow | Implemented |
| 8 | Deployment reliability + documentation closeout | Implemented |

Slice 8: `pool_pre_ping` on every engine (a PostgreSQL test kills the API's pooled connections
and the next request still succeeds; locally, a real PostgreSQL restart failed no request);
database-down behavior reproduced locally (500 with the `OperationalError` logged, recovery
without restarting the API); README › Deployment; `AGENTS.md` updated for SQLite locally and
PostgreSQL in production. Audit on 2026-10-25: every item of the milestone's definition of done
checked against CI, the repository, and the live deployment.

**Active milestone: 7 — Guardrailed AI Meal Planning.** Slices land one at a time, each only after
the developer authorizes it; nothing below is implemented unless marked so. The durable decisions
are in `docs/architecture.md` › AI Meal Planning and `docs/domain-rules.md` › AI Trust Boundary.

**Problem.** Recommendations answer "what single recipe should I make now?", scoring one recipe at
a time. Milestone 7 addresses a different question: given what is in the fridge, what has been
eaten, the nutrition left for the day, what should be used soon, and the user's constraints,
plan the next several meals. That is sequential: each chosen meal changes the inventory and
nutrition state the next choice should see.

**Why AI, and how it is judged.** The deterministic engine stays the right tool for ranking one
meal. AI is introduced only where it may add value: planning several steps, combining hard
constraints with softer natural-language preferences, deciding which state to inspect, and
explaining tradeoffs. A deterministic baseline planner solves the same problem so the AI can be
measured against it on plan validity, constraint compliance, planning quality, latency, and
cost. If the AI does not beat the baseline or otherwise add clear value, the repository will say
so.

**Scope.**

- Claude selects, sequences, and explains meals from FridgeFit's **existing recipes**; it never
  invents recipes or nutrition values.
- Planning is user-triggered and **read-only**. Meals are still logged only through the existing
  confirmation flow.
- One public capability, conceptually `POST /meal-plans`; its contract is approved in Slice 7.
  Internal tools are in-process Python calls, never public endpoints.
- A bounded control loop with one correction attempt, deterministic validation of every plan,
  and the deterministic plan as fallback. Step limits and other bounds are set in Slice 4.
- Every AI run records provider, model, token usage, model and tool calls, latency, validation,
  correction and fallback outcomes, and estimated cost. Raw tokens are authoritative; prices live
  in one place and are labeled as estimates.
- The model comes from configuration. No default is chosen before evaluation.
- Out of scope: self-service kitchen setup (see Intentionally Unimplemented), AI recipe
  generation, and any agent framework, embeddings, memory, multi-agent design, queue, or write
  tool.

Milestone 7 slices:

| Slice | Scope | Status |
|---|---|---|
| 0 | Milestone activation and AI architecture documentation | Implemented |
| 1 | Deterministic multi-meal planning baseline: simulate each chosen meal, no database writes, reuse existing calculations | Implemented |
| 2 | Planning evaluation harness: reproducible scenarios and metrics (feasibility, constraints, macro deviation, expiring-food use, diversity) | Implemented |
| 3 | Read-only AI tool boundary: a few narrow, structured, in-process tools; no mutation or broad database access | Implemented |
| 4 | Bounded Claude planning loop: configured model, server-side key, structured tool calls, step and size limits, usage and latency captured | Implemented |
| 5 | Deterministic validation and fallback: one bounded correction, otherwise the baseline plan | Implemented |
| 6 | Cost/performance instrumentation and comparative evaluation: baseline vs. Claude configuration(s) | Implemented |
| 7 | Meal planning HTTP API (`POST /meal-plans`, contract approved first); no mutation | In progress (endpoint, daily AI cap, and deployment configuration implemented; deployed verification next) |
| 8 | Minimal frontend planning experience; logging a planned meal stays the existing confirmation | Not started |
| 9 | Evaluation and documentation closeout: chosen configuration and why, measured results, failure modes | Not started |

Milestone 7 is complete only after the deployed planning workflow has been exercised end to end,
and it claims AI improves planning only if the evaluation supports that.

## Known Follow-ups

Deliberate shortcuts and cleanup, recorded so they are not lost:

- Two confirmations with different keys can both read the same stock and overwrite each other's
  decrement (lost update). Acceptable under the single-user assumption; revisit if that changes.
  (The same-key race tests pass on PostgreSQL.)

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
- "Today" and default meal times come from the server's clock (the frontend sends neither). The
  deployed server's clock is UTC, so `render.yaml` pins `TZ=America/New_York`, the single
  user's timezone; a user elsewhere would need a different `TZ`, or the frontend sending local
  dates and times. Meal 8 on the deployed database was logged before `TZ` was set and is
  stamped in UTC.
- The deployed free PostgreSQL database (created 2026-10-24) expires on **2026-11-23** and is
  deleted 14 days later; it has no backups. Before then: upgrade it, or let it lapse and rebuild
  (new database, deploy, `scripts/seed_demo.py --insert-only`).

## Implemented

### Persistence (`app/persistence/`)

Models: Ingredient, InventoryBatch, Recipe, RecipeIngredient, MealLog, MealLogIngredient,
NutritionGoal, MealFeedback.

`database.py`: `get_database_url()` returns the `DATABASE_URL` environment variable, read when
called, or `sqlite:///fridgefit.db` when it is unset or empty. A PostgreSQL URL without a driver
(`postgres://` or `postgresql://`, as hosts hand out) is rewritten to `postgresql+psycopg://`, so
the driver is psycopg 3 whatever SQLAlchemy version is installed. The foreign-key `PRAGMA` hook
runs only on SQLite connections. `get_engine()` sets `pool_pre_ping=True`: before reusing a
pooled connection it runs a tiny check query and reconnects if the connection died while idle
(for example after a database restart), so that request does not fail. `Base.metadata` has a
naming convention for primary keys, foreign keys, unique constraints, and indexes.

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
| Recipe consumption planning | `recipe_consumption.py` | `plan_recipe_consumption(recipe, servings, batches_by_ingredient)` |
| Meal confirmation | `meal_confirmation.py` | `confirm_meal(session, recipe, *, servings, consumed_at, name=None, allow_shortfall=False, idempotency_key=None)` |

Implementation behavior worth knowing:

- **Recipe macros** accept optional per-ingredient quantity overrides keyed by
  `RecipeIngredient.id`. With no overrides, the recipe's stated quantities are used.
- **Remaining macros** subtract only MealLogs whose `consumed_at` falls on the same calendar day as
  the requested date. A `ValueError` is raised if no goal is effective yet.
- **Inventory aggregation** sums `quantity_remaining` per ingredient.
- **FEFO planning** is read-only. It returns a plan, and returns a partial plan (not an error) when
  inventory is insufficient.
- **Recipe consumption planning** is read-only. It scales every ingredient to `servings`, plans
  FEFO draws from the given batches per ingredient, and returns each line's draws, the fulfilled
  quantity per recipe ingredient, and any shortfalls (needed vs. available). Batches may be any
  objects with `ingredient_id`, `quantity_remaining`, `use_by_date`, and `purchased_at`.
- **Meal confirmation** scales every ingredient to the required `servings` (cook only what is
  eaten), plans every ingredient with `plan_recipe_consumption` before mutating anything, then
  commits the MealLog, MealLogIngredients, and batch decrements in one transaction.
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

### Deterministic meal planning (`app/domain/meal_planning.py`, Milestone 7 Slice 1)

`plan_meals(recipes, batches, as_of, remaining_macros, rating_summaries, meal_count,
max_prep_minutes=None, servings_per_meal=1)` is the non-AI baseline planner. It is pure: it
reads in-memory copies and writes nothing. Decisions approved for it:

- Plans the rest of one day: `meal_count` meals (a positive whole number), each
  `servings_per_meal` servings (any positive number, as in meal confirmation; default 1, the
  original Slice 1 decision), optionally only recipes with `prep_minutes <= max_prep_minutes`.
  The plan records `servings_per_meal`.
- **Ranking scores one serving**, as recommendations always do; only the simulation (consumption,
  shortfalls, macros) uses `servings_per_meal`. With more than one serving, the baseline can
  therefore pick a recipe that is short of stock or over budget at the real portion; the plan
  reports it but does not avoid it. Deliberate: a limitation the AI planner may improve on.
- **Greedy.** Each step ranks the recipes not yet planned with `recommend_recipes` against the
  simulated state, takes the best, and simulates eating it. No recipe repeats within the plan.
- **Simulation on plain copies.** Inventory is `SimulatedBatch` values (`id`, `ingredient_id`,
  `quantity_remaining`, `use_by_date`, `purchased_at`); each planned meal produces new copies
  with its FEFO draws removed (via `plan_recipe_consumption`, the same rule meal confirmation
  uses). Database objects are never touched. The step is public as
  `simulate_meal(recipe, batches, remaining, servings)`, returning a `MealSimulation` (consumed,
  batch draws, macros, shortfalls, remaining after, inventory after); it simulates any recipe,
  including one the recommender would exclude, so later callers can replay a chosen sequence.
- Because every step ranks against the simulated inventory, **availability and expiry urgency
  are recalculated** after each meal: urgent stock a planned meal uses up stops driving urgency.
- **Partially available recipes may be planned.** They draw only what is on hand; their
  `consumed` quantities (per ingredient), `batch_draws` (per batch), and macros reflect that,
  and their `shortfalls` are reported.
- **Macros guide and are reported, never enforced.** With a nutrition goal, each meal's macros
  come off the remaining amounts, so the next step's macro fit uses them; each meal reports
  `remaining_after` and the plan `remaining_at_end`. Without a goal these are None.
- **Ties** (equal combined score): a rated recipe before an unrated one, then the higher average
  rating, then the lower recipe id. Because enjoyment is `(average - 1) / 4` and unrated recipes
  score 0.5, the average-rating step only decides when other components offset a different
  average exactly, which is rare in practice.
- The plan may hold fewer meals than requested (`meals_requested` keeps the request) when no
  eligible recipe is left.
- `validate_plan_request(meal_count, max_prep_minutes, servings_per_meal)` checks a request's
  numbers; `ranking_key` is the tie-break order (public so other callers rank identically).
- `replay_plan(chosen, recipes, batches, as_of, remaining, ratings, meal_count, max_prep_minutes,
  servings_per_meal)` (Slice 5) replays a proposed recipe sequence through the same ranking and
  simulation and returns a `ReplayedPlan`: the `MealPlan` FridgeFit computes for it and every
  problem. A sequence is valid only when it has no `plan_violations`, every recipe is eligible
  at its point in the sequence (otherwise `plan` is None), and it has no fewer meals than
  requested while an eligible recipe within the prep limit remains. Shortages are allowed and
  reported, as for the baseline. Replaying the baseline's own choices reproduces the baseline's
  plan exactly in every evaluation scenario (tested).
- `plan_violations(recipes, known_recipe_ids, meal_count, max_prep_minutes)` lists the hard
  constraints any sequence of recipes breaks (more meals than requested, unknown recipes,
  repeats, over the prep limit), whoever proposed it. The evaluation's
  `hard_constraint_violations` calls it.

`app/application/meal_planning.py`: `get_meal_plan(session, as_of, meal_count,
max_prep_minutes=None, servings_per_meal=1)` loads the inputs with `load_recommendation_inputs`,
copies the batches into `SimulatedBatch` values, and calls `plan_meals`. Read-only. `POST
/meal-plans` does not call it: that endpoint's baseline comes from `plan_day` (Slice 7).

### Planner evaluation (`app/evaluation/`, Milestone 7 Slice 2)

Measures planners on fixed scenarios, before any AI exists, so later configurations are compared
on the same inputs. Not used by the API.

- `scenarios.py`: seven in-memory scenarios built from one catalog of 10 ingredients and 6 recipes,
  with explicit ids and a fixed date (`SCENARIO_DATE`, 2026-03-10), so runs are reproducible and
  need no database: `well-stocked`, `short-inventory`, `expiring-today`, `macros-nearly-used`,
  `tight-prep-limit`, `high-protein-preference`, `bigger-meals` (2 meals of 2 servings). Each
  holds stock, a daily goal (2200 kcal, 160 g protein, 220 g carbs, 70 g fat), what was eaten
  already, ratings, the request (meal count, prep limit, servings per meal), and an optional
  soft preference with a machine-checkable rubric (`MinPlannedMacro`, `ExcludeRecipe`).
- `metrics.py`: `score_plan(scenario, plan)` reads only the scenario and the returned plan, so any
  planner can be scored the same way. Metrics:
  - hard-constraint violations: more meals than requested, repeats, unknown recipes, over the
    prep limit;
  - completeness (meals planned vs. requested) and inventory shortfalls per meal;
  - macros, directional like macro fit: signed end-of-day remaining per macro; calories, carbs,
    and fat **over** the goal; protein **short** of it, and protein beyond 1.5× the goal
    (`PROTEIN_ACCEPTABLE_EXCESS`);
  - expiring food: of the batches due within `EXPIRING_SOON_DAYS` (expired stock excluded), how
    many the plan uses up and the mean share used;
  - soft-preference rubric checks (pass/fail with the measured value).

  `evaluate_baseline()` runs `plan_meals` on every scenario and returns an `EvaluationRun`.
- `results.py`: Pydantic models (immutable, finite numbers, no unknown fields, ranges such as
  counts ≥ 0) for each scenario's result and the run summary.
- **AI configurations** (Slice 6). `evaluate_ai(config, client, runs, cap)` plans every
  scenario `runs` times with `plan_day` and scores the returned plan (AI or fallback) with the
  same `score_plan`. Each result also carries an `AttemptResult`: source, outcome, fallback
  reason, rejected plans, model and tool calls, invalid tool calls, raw input/output/cache
  tokens, model and total seconds, and estimated cost; the run summary adds an `AISummary`
  (AI plans used, fallbacks, plans used after a correction, tokens, mean/max latency, total
  estimated cost). A `SpendingCap` shared across configurations stops new attempts once the
  estimate reaches it (checked before each attempt, so at most one attempt over); the run then
  records `stopped_early`. A model with no listed price is refused.
- `pricing.py`: the only place prices live, `PRICES` keyed by (provider, model) with input,
  output, cache-read, and cache-write US dollars per million tokens, labeled as Anthropic list
  prices as of `PRICES_AS_OF` (2026-10-06): Haiku 5.5 $0.10/$0.50, Sonnet 5.5 $2/$10, Opus 5.5
  $4/$20. `estimate_cost(usage)` derives cost from the raw tokens, which stay authoritative.
- `scripts/evaluate_planner.py` writes one JSON file per planner to `evaluation-results/`
  (git-ignored; `:` in a planner name becomes `_`) and prints summaries. Without flags it runs
  the baseline only, with no network or cost. `--live --config MODEL:RUNS` (repeatable) adds
  Claude configurations at `--effort` (default low) under `--max-cost-usd` (default 1.00); it
  refuses `--config` without `--live`, `--live` without `ANTHROPIC_API_KEY`, and unpriced
  models, before anything runs.

Baseline on 2026-10-25: 7/7 plans complete and hard-constraint compliant; 6/7 without shortfalls
(`short-inventory` plans one partial meal); `macros-nearly-used` ends 306 kcal over the goal
(greedy weighs macro fit at 0.2 of the score); `expiring-today` uses 29% of the expiring stock;
protein ends 50–100 g short in every scenario (one serving per meal); `high-protein-preference`
plans 74 g of protein and fails its "planned protein >= 85 g" check (the baseline ignores the
preference text) while passing "no Bean burrito" by chance; `bigger-meals` ends 210 kcal under
the calorie goal and 18 g over on protein (within the 1.5× allowance).

**Live AI evaluation (Slice 6, 2026-10-26).** `--live --config claude-haiku-5-5:3 --config
claude-sonnet-5-5:1 --config claude-opus-5-5:1`, all at effort low: 35 attempts (Haiku three
runs per scenario, Sonnet and Opus one, chosen to fit the available API credit), estimated
$0.48 of a $1.00 cap. The high-protein rubric bar was then 90 g; outcomes below use the
corrected 85 g bar, derived from the saved protein totals without a re-run.

- **Reliability:** 35 of 35 attempts produced a valid plan on the first submission: no
  corrections, no fallbacks, no invalid tool calls, 3–4 model calls each. The correction and
  fallback paths were therefore never exercised live (they are covered by fake-client tests).
- **Plan quality against the baseline**, scored with the same metrics:
  - `macros-nearly-used`: every model, every run planned yogurt bowl + omelette and ended
    **64 kcal over** the calorie goal, against the baseline's 306. The one clear AI win.
  - `high-protein-preference`: every model, every run planned chicken bowl + salmon plate,
    **88.8 g** of protein, the most any valid plan reaches (baseline 74 g). Passes the 85 g
    check the baseline fails; both avoid the burrito.
  - `well-stocked`: oats + bowl + salmon, 46 g protein short (baseline 51 g). Slightly better.
  - `short-inventory`: Haiku and Sonnet chose omelette + oats + yogurt bowl, avoiding the
    baseline's shortfall but ending 89 g protein short (baseline 70 g); Opus chose the
    baseline's recipes. A tradeoff, not an improvement.
  - `expiring-today`, `tight-prep-limit`, `bigger-meals`: the same recipes as the baseline
    (order sometimes different); expiring food used stays at 29%.
- **Consistency (Haiku, 3 runs):** the same recipe set in all runs for 6 of 7 scenarios (order
  varies); in `bigger-meals` one run chose oats over the salmon plate (3 g protein short).
- **Cost and latency per attempt** (estimated from raw tokens; about 8,800–9,400 input tokens
  each, and on average 684 output tokens for Haiku, 353 for Sonnet, 402 for Opus):

  | Model | Est. cost | Mean / max time | Plans |
  |---|---|---|---|
  | `claude-haiku-5-5` | $0.0013 | 6.2 s / 10.6 s | Same as Sonnet in every scenario |
  | `claude-sonnet-5-5` | $0.021 | 4.9 s / 7.5 s | Same as Haiku |
  | `claude-opus-5-5` | $0.043 | 7.5 s / 10.9 s | Differs only in `short-inventory` |

- **Recommended configuration: `PLANNER_MODEL=claude-haiku-5-5`, `PLANNER_EFFORT=low`**
  (developer's decision). It plans like Sonnet at about 1/16 of the cost and like Opus at
  about 1/33, with acceptable latency. The code keeps no default model; deployment sets it.
- **What the AI adds, honestly:** a clear improvement where the greedy baseline's weighting
  ignores the calorie budget, a measurable one when the user states a preference, a small one
  on protein when well stocked, and a tradeoff with short stock; elsewhere it ties the
  baseline, plus a model-written explanation.
- **Not shown by this evaluation:** the correction and fallback paths working live; effort
  levels other than low; scenarios beyond these seven; one run per scenario for Sonnet and
  Opus says little about their consistency; prompt caching (no cache reads; input tokens
  dominate cost) as a possible saving.

### AI planning tools (`app/application/planning_tools.py`, Milestone 7 Slice 3)

The read-only tools an AI planner will use to inspect FridgeFit. Nothing calls Claude yet (Slice
4); no tool is an HTTP endpoint, and none writes anything.

- **One snapshot per request.** `load_planning_snapshot(session, request)` validates the
  `PlanningRequest` (date, meal count, prep limit, servings per meal, preference text) with the
  planner's `validate_plan_request`, loads the inputs once with `load_recommendation_inputs`, and
  copies stock into `SimulatedBatch` values. Every tool reads only that snapshot.
- **Three tools**, each calling the same domain functions as the deterministic planner:
  - `get_planning_context`: the request, today's remaining macros, stock per recipe ingredient
    (on hand, unit, earliest use-by, quantity due within `EXPIRING_SOON_DAYS`; ingredients no
    recipe uses are left out), and the ranked candidates within the prep limit, in the
    baseline's order (`ranking_key`), capped at `MAX_CANDIDATES` (10) with the total reported.
  - `get_recipe(recipe_id)`: lines per serving against stock, prep time, whether it is within
    the limit and eligible, macros per serving.
  - `simulate_plan(recipe_ids)`: the given recipes in order, each simulated with `simulate_meal`
    at the request's servings and chained on the stock the previous meal left; consumption,
    shortages, macros, remaining macros, a warning for a recipe the recommender would exclude,
    and the `plan_violations` of the sequence. Violations are reported, not refused.
- **Pydantic input and output.** Inputs forbid unknown fields and take strict integers;
  `tool_definitions()` gives each tool's name, description, and input schema generated from its
  input model, in the Messages API's tool shape. Outputs are Pydantic models serialized to JSON,
  with quantities and macros rounded to 1 decimal and scores to 2 (display only).
- **Bad input never raises.** `run_tool(snapshot, name, input)` returns a `ToolResult` (JSON text,
  `is_error`). An unknown tool, invalid input, or unknown recipe id gives a JSON `{"error": ...}`
  with `is_error` set, which the model can correct.
- Claude chooses recipes and their order only; servings come from the request.

### Claude planning loop (`app/application/ai_planner.py`, Milestone 7 Slice 4)

`run_ai_planner(snapshot, config, client)` lets Claude inspect the snapshot through the planning
tools and propose a plan. It is explicit Python control flow over the Anthropic SDK's
`messages.create` (`anthropic>=2.3`; no agent framework), returns an `AIPlanAttempt`, and never
raises for model or provider problems. It writes nothing.

- **Configuration.** `planner_config_from_env()`: `PLANNER_MODEL` with no default (unset means
  AI planning is off), `PLANNER_EFFORT` defaulting to `low` (one of low, medium, high, xhigh,
  max). `make_client()` uses the server's `ANTHROPIC_API_KEY` (no key, no client) with SDK
  retries off, so the time budget bounds every attempt. `daily_limit_from_env()` reads
  `PLANNER_DAILY_LIMIT` (a whole number; unset means no limit, 0 means no AI attempts) into a
  `DailyLimit`: an in-memory count per server-local day, guarded by a lock because sync routes
  run in a thread pool. It resets at midnight and on restart, and each process has its own
  count. `baseline_result(snapshot, reason, attempt)` returns the baseline `PlanningResult`.
- **Limits** (`PlannerConfig`): at most 6 model calls, `max_tokens` 4096 per call, 60 s for the
  whole loop; each call's timeout is the time left. Adaptive thinking with the configured effort;
  no sampling parameters.
- **Tools.** The three read-only tools plus `submit_plan(recipe_ids, explanation)`, all with
  `strict: true`. Each reply is appended unchanged (thinking blocks included) before one user
  message carrying every tool result by id.
- **Validation and one correction** (Slice 5). Every `submit_plan` is checked with
  `proposal_problems(snapshot, recipe_ids)` (`planning_tools.py`: unknown ids, else
  `replay_plan`'s problems). A valid plan ends the loop. A rejected plan's tool result lists
  every problem, and Claude may resubmit in the same conversation, once
  (`PlannerConfig.max_corrections`), within the same 6 calls and 60 s; a second rejection ends
  the attempt as `invalid_plan`. Malformed `submit_plan` input is an error result too, but is not
  a rejected plan.
- **Outcomes.** `submitted` (a plan that passed validation), `invalid_plan`, `refusal`, `truncated`
  (`max_tokens`), `no_plan` (stopped without `submit_plan`), `step_limit`, `time_limit` (budget
  spent or call timed out), `provider_error` (connection, rate limit, other API errors; no server
  fallback model).
- **Usage per attempt** (`AttemptUsage`): provider, model, effort, input/output and cache tokens
  summed over calls, model calls, tool calls, invalid tool calls, rejected plans, model seconds,
  total seconds.
  Estimated cost is derived from these in Slice 6.
- **Choosing the plan** (Slice 5): `plan_day(snapshot, config, client)` returns a
  `PlanningResult`: the `plan` (a `MealPlan`), its `source` (`ai` or `baseline`), the AI's
  `explanation` (model-written text, never parsed for numbers; only with an AI plan), the
  `fallback_reason`, and the `attempt` (with its usage) when one ran. The AI's plan is used only
  when the attempt ends `submitted`; it is replayed again with `replay_proposal`, so every number
  is FridgeFit's and nothing unvalidated is returned. Otherwise the baseline (`plan_meals`) is
  returned: when `PLANNER_MODEL` or `ANTHROPIC_API_KEY` is missing (no call is made), or with the
  attempt's outcome and detail as the reason. Errors in FridgeFit's own code are not caught.
- Tested with a scripted fake client (`tests/test_ai_planner.py`); no test calls the API.
- One live run on 2026-10-26 (`expiring-today`, 2 meals, no prep limit, `claude-haiku-5-5`, effort
  low): `submitted` `[2, 4]` (Spinach omelette, Salmon rice plate, the same plan as the baseline)
  in 3 model calls and 3 tool calls with no invalid input; 8,908 input and 773 output tokens;
  9.1 s. Its explanation's figures (748 kcal, 56 g protein; about 1,450 kcal left) match
  `simulate_plan`. No cache reads (nothing is marked for caching).

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
- `create_app` also reads the AI planner's settings once (`planner_config_from_env()`,
  `make_client()`, `daily_limit_from_env()`) into `app.state.planner_config`,
  `app.state.planner_client`, and `app.state.planner_limit` (a bad `PLANNER_EFFORT` or
  `PLANNER_DAILY_LIMIT` stops startup; a None config or client turns AI planning off), and calls
  `logging.basicConfig(level=INFO)` so FridgeFit's own log lines reach the server log next to
  Uvicorn's. Tests replace these `app.state` values with a scripted fake client.
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
  `recommendations.py`, `meals.py`, `meal_plans.py`), each holding its `APIRouter` and Pydantic schemas.
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
  - `POST /meal-plans` (Milestone 7 Slice 7): plans the rest of a day and writes nothing. Body
    (unknown fields → 422): `meal_count` 1-5 (required), `max_prep_minutes` 1-240,
    `servings_per_meal` > 0 (default 1), `preference` (free text, at most 300 characters, given
    to the AI planner only), `as_of` (defaults to today on the server's clock). Always 200 with
    `source` (`ai` or `baseline`), `explanation` (the AI's text; null for the baseline),
    `fallback_reason`, `meals` (per meal: `recipe_id`, `name`, `prep_minutes`, `servings`,
    `ingredients_used` and `shortages` per ingredient with name and unit, `macros`,
    `remaining_after`), and `remaining_at_end` (null without a nutrition goal). The plan comes
    from `plan_day`. `fallback_reason` is a coarse code taken from the attempt's recorded
    outcome, never from its text: null when the AI plan is used, `ai_disabled` (no model or key
    configured), `ai_plan_invalid` (still invalid after the one correction), `ai_failed` (any
    other outcome: provider error, refusal, truncation, no plan, step or time limit), and
    `ai_limit` (today's AI attempts reached `PLANNER_DAILY_LIMIT`; Claude is not called).
    Only requests that would call Claude count, and the day is the server's, not `as_of`, so
    changing `as_of` does not reset the cap. Provider error text, tokens, latency, and estimated
    cost (`estimate_cost`) go to one INFO server log line per request, never to the response.
    The route is a plain `def`, so FastAPI runs the blocking Claude loop (up to 60 s) in its
    thread pool instead of stalling other requests. No authentication: anyone who can reach the
    API can spend AI credit, which the daily cap bounds.

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
- `recommendations.py`: `get_recommendations(session, as_of)` passes the result of
  `load_recommendation_inputs(session, as_of)` to `recommend_recipes`. The loader returns a
  `RecommendationInputs` tuple, reusable by other workflows: recipes, batches with stock,
  remaining macros (via `get_nutrition_state`), each recipe's rating average and count
  (`AVG`/`COUNT ... GROUP BY recipe_id`, manual meals excluded, `AVG` cast to float so
  PostgreSQL's NUMERIC does not arrive as `Decimal`), the recent-frequency window's meals, and
  each recipe's last-eaten date (`MAX(consumed_at) ... GROUP BY recipe_id`). Neither meal history
  nor ratings are loaded in full. Read-only.
- `meals.py`: `confirm_recipe_meal(session, recipe, ...)` returns the existing MealLog (with
  `created=False`) when the idempotency key was already confirmed; otherwise calls
  `confirm_meal`, which writes the key in its own atomic commit. If that commit fails with an
  `IntegrityError` while a key was given, it rolls the session back and looks the key up again:
  found means another request committed it first, so that MealLog is returned as a replay
  (`created=False`); not found means an unrelated violation, which is re-raised. A shortfall with
  a key gets the same second lookup (no rollback needed: nothing was written), so a shortfall
  caused by a same-key winner replays instead of returning 409.

### Deployment configuration (`render.yaml`)

Applied on 2026-10-24 (Slice 6) as a Render Blueprint. It declares:

- `fridgefit-api`: free Python web service. Build `pip install .` (runtime dependencies only).
  Start `alembic upgrade head && uvicorn app.api.main:app --host 0.0.0.0 --port $PORT`: the free
  plan has no pre-deploy command, so migrations run before every start, a no-op when current. On
  a paid plan, `alembic upgrade head` would move to a pre-deploy command. Health check
  `/health`. Environment: `PYTHON_VERSION` 3.12, `TZ` `America/New_York`, `DATABASE_URL`
  linked from the database, and `FRONTEND_ORIGIN=https://fridgefit-3f2a.onrender.com`, the
  static site's exact origin (committed: it is public). Auto-deploy is set in the dashboard to
  "After CI Checks Pass".
  AI planning (Milestone 7 Slice 7): `PLANNER_MODEL=claude-haiku-5-5` and `PLANNER_EFFORT=low`
  (the configuration the evaluation recommended), `PLANNER_DAILY_LIMIT=50` (about $0.07 a day
  at the measured $0.0013 per Haiku plan), and `ANTHROPIC_API_KEY` declared with
  `sync: false`: its value is entered in the Render dashboard and never committed. Until it is
  set, `POST /meal-plans` returns the baseline with `ai_disabled`.
- `fridgefit` (Slice 7): static site at `https://fridgefit-3f2a.onrender.com` (Render added the
  suffix: `fridgefit.onrender.com` is an unrelated site), built from `frontend/`. Build
  `npm ci && npm run build` with `NODE_VERSION` 22 (as in CI) and
  `VITE_API_BASE_URL=https://fridgefit-api.onrender.com`, which Vite bakes into the bundle;
  publishes `frontend/dist` from Render's CDN. No rewrite
  rules: the frontend is one page with no client-side routes. The build was rehearsed on a copy
  of `frontend/`: it succeeded and the bundle holds the production API URL, not the local
  default.
- `fridgefit-db`: free PostgreSQL 16, database and user `fridgefit`.
- Both in the `virginia` region (US East), so the API reaches the database over Render's private
  network. A database's region is fixed when it is created.
- No secrets in the file. Rehearsed locally (clean virtualenv, the exact build and start
  commands, an empty PostgreSQL database and a plain `postgresql://` URL): the first start
  migrated, `/health` and CORS answered as configured, and a restart ran no migration and kept
  the data.

### Deployment (Slice 6)

- API: `https://fridgefit-api.onrender.com` (`fridgefit-api`, free, Virginia). Database:
  `fridgefit-db`, free PostgreSQL 16, Virginia, created 2026-10-24 (see Known Follow-ups for
  its expiry).
- First deploy: the build succeeded with `PYTHON_VERSION` 3.12; the start command ran the
  baseline migration on the empty database (`Running upgrade -> d22b106d0d3b`), Uvicorn bound
  to Render's `$PORT`, and the health check passed.
- Demo data loaded once from the developer's machine with the database's external URL:
  `DATABASE_URL=... scripts/seed_demo.py --insert-only`.
- Verified against the deployed API on 2026-10-24: `/health` 200; `/recommendations` ranked
  recipes from PostgreSQL; `POST /recipes/1/confirm` with an `Idempotency-Key` → 201 (meal 8),
  the same key again → 200 with the same meal, and inventory decreased once (chicken
  1000 → 850, rice 2000 → 1850, broccoli 300 → 200); after a service restart the meal was still
  listed and no migration ran; `POST /recipes/9999/confirm` → 404, visible in Render's logs.
- Render probes `HEAD /` and `GET /`; both return 404 because the API has no root route, which
  is expected.

### Deployment (Slice 7)

- Frontend: `https://fridgefit-3f2a.onrender.com` (static site `fridgefit`), serving the bundle
  built from this repository (`assets/index-Ci82eVnf.js` at the time), which calls
  `https://fridgefit-api.onrender.com`. Auto-deploy: "After CI Checks Pass", like the API.
- CORS verified against the live API on 2026-10-25: requests from the static site's origin get
  `access-control-allow-origin: https://fridgefit-3f2a.onrender.com`; requests from the
  unrelated `https://fridgefit.onrender.com` get no CORS header.
- Browser workflow verified by the developer on the deployed site on 2026-10-25: the dashboard
  connected and loaded ranked recommendations with their reasons; a recommendation's detail
  opened; logging a meal updated inventory, remaining macros, and today's history (at local
  Eastern time); rating the meal showed it as rated; light and dark mode both rendered
  correctly.
- On the free plan a sleeping API makes the first load wait (the page itself loads at once,
  since static sites do not sleep); the dashboard shows its loading or "Offline" state until the
  API wakes.

### Demo seed (`scripts/seed_demo.py`)

- Run from the repository root against the app's database (`get_database_url()`:
  `DATABASE_URL` or `fridgefit.db`). The dataset is inserted through the ORM (not the HTTP API)
  by `insert_demo_data(session, now)`, shared by two modes:
  - Default, `.venv/bin/python scripts/seed_demo.py`: local reset. Drops every table, including
    Alembic's version table, rebuilds them with `alembic upgrade head`, then inserts, so each run
    gives the same known state. Refuses (exit with a message naming the database, nothing
    touched) when the database
    is not SQLite.
  - `--insert-only`: for any database, including deployed PostgreSQL. Never drops or alters
    anything; inserts only when the database is at the latest migration and every table is
    empty, and otherwise refuses with the reason and the database's name, never its
    credentials (nothing written). A `DATABASE_URL` that is set but empty is refused rather
    than treated as the local SQLite file.
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

395 tests across `tests/test_models.py`, `tests/test_database.py`, `tests/test_migrations.py`,
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
- `main` is protected: changes merge only through a pull request whose four required checks pass
  ("Lint and test" on Python 3.11 and 3.12, "Test on PostgreSQL 16", and "Frontend build"); no
  approval is required, and the admin can bypass in an emergency.
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
- Docker (not planned unless deployment needs it)
- Redis, queues, and microservices
