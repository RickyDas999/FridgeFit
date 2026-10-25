# FridgeFit — Architecture

Durable architectural decisions. Changes to anything here are architecture decisions and must be
approved by the developer before implementation.

For product/domain invariants, see `docs/domain-rules.md`. For what is currently built, see
`docs/current-milestone.md`.

---

## Shape of the System

- FridgeFit should initially be a **modular monolith**.
- The architecture must remain simple enough to understand and explain end-to-end.

## Workload Assumptions

FridgeFit is a single-user application in V1:

- approximately 1 daily active user;
- low concurrency;
- small dataset.

Concurrent writes are not currently a meaningful concern.

## Stack

- Python 3.11+
- SQLAlchemy 2.x
- SQLite for local development and tests; PostgreSQL in production (see Environments and
  Deployment), through the psycopg 3 driver
- Alembic for schema migrations of persistent databases
- FastAPI for the V1 HTTP API
- Pydantic for HTTP request and response schemas
- React + TypeScript + Vite for the demo frontend (a Node.js toolchain confined to `frontend/`)
- pytest
- Ruff for linting, pinned to an exact version and configured in `pyproject.toml`
- GitHub Actions for CI: lint and tests on every pull request and every push to `main`; the same
  test suite also runs against a PostgreSQL service container, so PostgreSQL behavior is tested
  for real, not mocked
- An advisory Claude review in GitHub Actions, run on request by labeling a pull request
  `ai-review`: one review request, plus at most two bounded format-repair requests. AI review
  never blocks merging and never writes code; its findings are hypotheses for the developer.

SQLite matched the original single-user, local workload and remains the local default.
Deployment adds requirements SQLite on a hosted filesystem cannot meet: data must survive
restarts and redeploys, and the schema must evolve without deleting data. That justifies
PostgreSQL in production; it is not a rewrite of local development.

## Environments and Deployment

Approved target (Milestone 6):

```text
Browser
  ↓ HTTPS
React static frontend   (Render Static Site)
  ↓ HTTPS
FastAPI web service     (Render Python Web Service, Uvicorn)
  ↓
PostgreSQL              (Render-managed)
```

- Database selection is by environment: `DATABASE_URL` set → use it; absent → the local SQLite
  file `sqlite:///fridgefit.db`. A fresh clone works with no configuration. Tests keep passing
  their own database URL to `create_app`.
- SQLite-specific behavior (such as the foreign-key `PRAGMA`) applies only to SQLite
  connections. Models and domain code are never forked by database.
- Alembic creates and evolves every real database's schema, local and production. SQLAlchemy
  models describe the desired schema; the migration history describes how a database gets there.
  Every schema change needs a migration, and every generated migration is reviewed, not accepted
  blindly.
- The API's startup never creates or alters tables. Migrations run as an explicit step
  (`alembic upgrade head`) before the API starts. On Render's free plan that step is the first
  half of the start command (`alembic upgrade head && uvicorn ...`), so it also runs on restarts
  (a no-op when current) and a failed migration keeps the API from starting; on a paid plan it
  belongs in the pre-deploy command instead.
- The destructive demo reset (drop and recreate every table) is local developer tooling only and
  must not be able to target a production database. Production demo data is loaded deliberately
  and never on every deploy; a restart or redeploy preserves database state.
- Configuration lives in a few environment variables (`DATABASE_URL`, `FRONTEND_ORIGIN`, `TZ`
  for the single user's timezone, and the platform's `PORT`), read directly; no settings
  framework unless the settings outgrow that. Secrets such as database credentials are never
  committed.
- Provider-specific configuration stays at the deployment boundary. Application code depends on
  `DATABASE_URL`, the frontend origin, and the port and start command, not on Render APIs.
- No Docker unless native Render Python deployment cannot meet a concrete need.
- Operations stay modest: `/health` checks API and database connectivity, and platform logs must
  be enough to diagnose failed startups, migrations, and requests. No metrics, tracing, or APM
  services without a concrete problem and developer approval.

## Infrastructure Not Used

Do not add any of the following unless a future requirement actually needs it:

- Redis;
- message queues;
- microservices;
- distributed infrastructure;
- multi-agent or agent-to-agent (A2A) architecture.

## External Boundaries

External services are allowed when they solve a real problem. They are **boundaries, not sources of
internal truth**: data crossing into FridgeFit is normalized and persisted or recalculated
deterministically before it is trusted.

Expected external boundaries:

- the Claude API, for user-triggered multi-meal planning: approved for Milestone 7 (see AI Meal
  Planning below), not yet implemented;
- a nutrition-data API: not approved; may not be implemented until explicitly requested.

AI recipe generation (see `docs/domain-rules.md` › AI Trust Boundary) is a separate capability
with no approved milestone.

## AI Meal Planning

Approved for Milestone 7. **None of this is implemented yet**; `docs/current-milestone.md` records
which slices have landed. These decisions constrain every Milestone 7 slice.

### Shape

```text
user planning request
  ↓
AI planning workflow (application layer)
  ↓  bounded, read-only internal tools
existing FridgeFit application/domain logic
  ↓
candidate multi-meal plan
  ↓
deterministic validation
  ↓  valid                       ↓  invalid
returned plan        one bounded correction → validate again → valid, or deterministic fallback
```

- Claude is a planning layer **above** the deterministic system. It may select, sequence, and
  explain meals from FridgeFit's existing recipes. Deterministic code remains authoritative for
  inventory quantities, nutrition values, recipe macros, FEFO, nutrition state, and whether a plan
  is feasible.
- **Read-only.** Planning never writes product state: no inventory changes, MealLogs, ratings, or
  edits to recipes, ingredients, or goals. Meals are still logged only through the existing
  confirmation workflow, explicitly by the user.
- **Internal tools are Python calls, not HTTP endpoints.** The planner calls application/domain
  functions (or thin read-only adapters) in-process. Tools are few, narrowly scoped, and
  structured; there is no broad database access and no mutation tool. The only public surface
  planned is one planning endpoint (`POST /meal-plans`, contract approved in its own slice).
- **Bounded control loop**, written as explicit Python control flow with the Anthropic SDK (no
  agent framework unless that becomes genuinely hard to maintain): a finite maximum number of
  steps, bounded context, a bounded number of recipes or candidates sent to the model, bounded
  output, no background execution, no recursive or multiple agents, no web access. The concrete
  limits are set in the implementation slice.
- **Deterministic validation** of every proposed plan: recipes exist, servings are valid,
  inventory is sufficient meal after meal, projected nutrition comes from deterministic
  calculation, and hard planning constraints hold. An invalid plan is never returned as valid.
- **Deterministic baseline and fallback.** A non-AI planner solves the same problem. It is both
  the comparison point for evaluating AI and the result returned when the AI fails (provider
  error, timeout, malformed output, invalid tool request, step limit) or its plan stays invalid
  after the one correction attempt.

### Configuration and secrets

- The model is explicit configuration, not hard-coded, so evaluations can compare configurations
  (baseline vs. a lower-cost model vs. a more capable one) on the same scenarios. No model is
  chosen as the default before evaluation.
- The Anthropic API key is server-side only: read from the environment, never committed, never
  sent to the frontend.
- Claude being unavailable must not break the application: existing recommendations and every
  other feature keep working without it.

### Cost, latency, and token observability

- Every AI planning run records evaluation metadata: provider, model, input/output (and total,
  if provided) tokens, model calls, tool calls/steps, end-to-end and model latency, validation
  result, whether a correction was needed, whether the fallback was used, and estimated cost.
- Raw token usage is authoritative; estimated cost is derived from it, so it can be recomputed
  when prices change. Prices live in one place, keyed by provider and model (input and output
  price per million tokens), labeled as evaluation estimates. Product behavior never depends on
  a price.
- Keep it simple: structured local results (e.g. JSON/JSONL) for evaluation; no analytics or
  tracing services, metrics infrastructure, or new database table unless a later slice shows one
  is necessary. Never log secrets; do not store full prompts or unnecessary personal data.

### Not used

LangChain, LangGraph, or other agent frameworks; vector databases or embeddings; long-term AI
memory; multi-agent systems; queues, background workers, or Redis; autonomous writes. Any of these
needs a concrete requirement and the developer's explicit approval.

## Code Layout

```text
alembic/           database migrations (env.py, versions/); configured by alembic.ini
render.yaml        Render Blueprint: the deployed web service and PostgreSQL database
app/
├── errors.py      InvalidInputError, shared by both layers
├── persistence/   database setup, enums, SQLAlchemy models
├── domain/        deterministic business logic and its input validators
├── application/   thin workflow functions spanning persistence + domain
└── api/           FastAPI app, routes, Pydantic schemas, error mapping
frontend/          React + TypeScript + Vite UI; talks to the backend only over the HTTP API
tests/             pytest suite; conftest.py gives each test a fresh SQLite or PostgreSQL database
.github/workflows/ CI workflow and the advisory AI review workflow
scripts/           developer and CI tooling (e.g. the AI review helper); not application code
AGENTS.md          contract for the independent AI reviewer
```

- Deterministic domain logic stays separate from persistence concerns where practical.
- Dependencies point one way: `domain` may import `persistence`, never the reverse. Anything both
  layers need, such as `InvalidInputError`, lives outside them in `app/errors.py`.
- Domain functions validate their inputs through `app/domain/validation.py` and raise
  `InvalidInputError`, rather than failing deep inside a calculation or returning a wrong result.
- Domain calculations are written as pure functions over already-loaded objects (no `Session`, no
  queries) where practical. A domain operation that must be atomic may take a `Session` and own the
  transaction boundary; `confirm_meal` is the current example.

## HTTP API and Application Layer

- `app/api/` owns HTTP concerns only: routing, Pydantic request/response schemas, translating
  errors such as `InvalidInputError` into HTTP responses, and the database session's lifetime.
  Each request gets its own session, which is closed when the request ends.
- `app/application/` holds plain functions that orchestrate one workflow spanning persistence and
  domain logic: load what the domain needs, call the domain function, save the result. A simple
  read or insert with no domain logic does not need an application function.
- Deterministic domain logic in `app/domain/` stays authoritative. API and application code never
  re-implement or override its calculations, rankings, or validation.
- Pydantic schemas are separate from SQLAlchemy models. Routes convert between them explicitly;
  ORM objects are never returned as response bodies, and request schemas never become models
  directly.
- Dependencies:
  - API routes may use persistence directly for simple resource reads and writes, and call an
    application workflow when persistence and domain logic must be orchestrated together.
  - Application workflows coordinate persistence and domain functions.
  - Domain functions use persistence models, as they already do.
  - Persistence never imports from domain, application, or API.
  - Do not create application functions merely to keep the layering symmetrical.
- Transaction ownership:
  - The API owns the request-scoped session's lifetime: it opens one session per request and
    closes it when the request ends.
  - An atomic mutation workflow owns its commit: it commits exactly once, at its end. A request
    that fails before that commit writes nothing; its changes are discarded when the session
    closes.
  - `confirm_meal` keeps its current behavior of committing its own atomic transaction.
  - Code that catches a failed commit (e.g. an `IntegrityError`) and keeps using the session must
    call `session.rollback()` first; SQLAlchemy refuses further queries until it does.
- Do not add repositories, generic service classes, Unit of Work frameworks, dependency-injection
  frameworks, or similar layers. FastAPI's built-in `Depends` is enough to provide the
  request-scoped session.

## Frontend

- `frontend/` is the UI boundary: a React + TypeScript app built with Vite. FridgeFit stays one
  repository and one modular-monolith backend; the frontend is a client of it, not a second
  backend.
- The frontend talks to FastAPI only through the HTTP API. There is no backend-for-frontend layer
  and no direct database access.
- The backend stays authoritative for every domain behavior: ranking, availability, expiry
  urgency, macro calculations, nutrition state, FEFO consumption, serving scaling, and MealLog
  snapshots. The frontend never re-implements or approximates these calculations; it displays
  what the API returns.
- Frontend state is presentation and interaction only: loading and error state, the selected
  item, form input such as servings, dialog state, and refetching API resources after a write.
- Start with native `fetch` and plain React state, and simple CSS. Do not add Next.js, Redux,
  Zustand, TanStack/React Query, or a UI component framework.
- CORS stays narrow: the local Vite dev origins, plus in production exactly the deployed
  frontend origin, read from the environment. Never `*`.
- In production the frontend is a static build (Render Static Site) whose API base URL is set at
  build time (`VITE_API_BASE_URL`).

### Visual design

- Theme: the inside of a fridge. Cool frost page, white shelf surface, deep pine ink, and one
  basil accent for actions, meter fills, and scores. Dark mode has its own validated values.
- Warm color means attention and nothing else: use-by amber for expiry, shortfalls, and
  missing ingredients; tomato for over budget and errors. Every text/background pairing meets
  WCAG AA (4.5:1).
- Type: one family, Atkinson Hyperlegible Next, self-hosted with `@fontsource` so the app needs
  no network for fonts. Sentence case; no all-caps labels; tabular figures only in columns.
- Hierarchy: the top recommendation is the one large element; everything else stays quiet.
  Structure carries meaning (rules between sections, tables for need/have), not decoration:
  no identical card grid, no middle-dot meta strings.
- Tokens (colors, spacing, radius) are CSS variables in `frontend/src/index.css`; components
  use them rather than literal values.

## Persistence Conventions

- Engines use `pool_pre_ping`, so a pooled connection that died while idle (database restart,
  dropped connection) is replaced before use instead of failing a request.
- SQLite foreign-key enforcement is enabled on every SQLite connection (`PRAGMA
  foreign_keys=ON` via a SQLAlchemy connect-event hook). SQLite leaves foreign keys unenforced by
  default; PostgreSQL enforces them natively.
- Clearly invalid values (negative quantities or macros, ratings outside 1–5, non-positive
  servings) are rejected by database `CheckConstraint`s.
- Rules a database constraint cannot express are enforced before each save with a SQLAlchemy
  `before_flush` hook in `models.py`. The current one rejects a Recipe with no ingredients, which
  a constraint cannot check because the Recipe row must exist before its ingredient rows.
- Recipe instructions are stored in a JSON column.
- Migrations live in `alembic/` (configured by `alembic.ini`); `alembic/env.py` uses
  `get_database_url()` and `Base.metadata`, and runs in batch mode on SQLite, which cannot alter
  most of a table in place.
- `Base.metadata` has a naming convention, so primary keys, foreign keys, unique constraints, and
  indexes get predictable names (`uq_meal_logs_idempotency_key`) a migration can refer to. Check
  constraints are named explicitly in the models.
- Test fixtures build tables with `Base.metadata.create_all` for speed; a migration test proves
  `alembic upgrade head` produces the same schema. Nothing else uses `create_all`.
- Queries that load a list eager-load the relationships the code reads (`selectinload`), so a
  list endpoint runs a fixed number of queries however many rows exist; lazy loading one query
  per row (N+1) is not acceptable on list paths. Single-item paths, whose cost is bounded by
  one row, may load lazily.
- Each list endpoint has a query-count test (the `count_queries` fixture in
  `tests/conftest.py`) asserting its count does not grow when more rows are added.
- When the domain needs only a summary of data that grows without bound (meal history,
  ratings), the query filters or aggregates in SQL (`WHERE`, `GROUP BY` with `MAX`, `AVG`,
  `COUNT`) and the domain function accepts that summary; the domain still owns every rule.
