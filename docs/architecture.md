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
  Deployment)
- Alembic for schema migrations of persistent databases
- FastAPI for the V1 HTTP API
- Pydantic for HTTP request and response schemas
- React + TypeScript + Vite for the demo frontend (a Node.js toolchain confined to `frontend/`)
- pytest
- Ruff for linting, pinned to an exact version and configured in `pyproject.toml`
- GitHub Actions for CI: lint and tests on every pull request and every push to `main`
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
- Alembic owns schema evolution of persistent databases. SQLAlchemy models describe the desired
  schema; the migration history describes how a real database gets there. Every schema change
  needs a migration, and every generated migration is reviewed, not accepted blindly.
- Production startup never uses `Base.metadata.create_all()` in place of migrations; migrations
  run as an explicit deployment step.
- The destructive demo reset (drop and recreate every table) is local developer tooling only and
  must not be able to target a production database. Production demo data is loaded deliberately
  and never on every deploy; a restart or redeploy preserves database state.
- Configuration lives in a few environment variables (e.g. `DATABASE_URL` and the deployed
  frontend origin), read directly; no settings framework unless the settings outgrow that.
  Secrets such as database credentials are never committed.
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

Expected future external boundaries:

- a nutrition-data API;
- the Claude API, for optional meal generation.

Neither is implemented. Neither may be implemented until explicitly requested.

## Code Layout

```text
app/
├── errors.py      InvalidInputError, shared by both layers
├── persistence/   database setup, enums, SQLAlchemy models
├── domain/        deterministic business logic and its input validators
├── application/   thin workflow functions spanning persistence + domain
└── api/           FastAPI app, routes, Pydantic schemas, error mapping
frontend/          React + TypeScript + Vite UI; talks to the backend only over the HTTP API
tests/             pytest suite; tests/conftest.py provides an in-memory SQLite session
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

- SQLite foreign-key enforcement is enabled on every SQLite connection (`PRAGMA
  foreign_keys=ON` via a SQLAlchemy connect-event hook). SQLite leaves foreign keys unenforced by
  default; PostgreSQL enforces them natively.
- Clearly invalid values (negative quantities or macros, ratings outside 1–5, non-positive
  servings) are rejected by database `CheckConstraint`s.
- Rules a database constraint cannot express are enforced before each save with a SQLAlchemy
  `before_flush` hook in `models.py`. The current one rejects a Recipe with no ingredients, which
  a constraint cannot check because the Recipe row must exist before its ingredient rows.
- Recipe instructions are stored in a JSON column.
- Until Alembic lands (Milestone 6 Slice 2), there are no migrations: the test fixture and the
  API's startup (lifespan) create missing tables with `Base.metadata.create_all`, which never
  alters existing tables. After it lands, schema changes follow the migration rules in
  Environments and Deployment.
- Queries that load a list eager-load the relationships the code reads (`selectinload`), so a
  list endpoint runs a fixed number of queries however many rows exist; lazy loading one query
  per row (N+1) is not acceptable on list paths. Single-item paths, whose cost is bounded by
  one row, may load lazily.
- Each list endpoint has a query-count test (the `count_queries` fixture in
  `tests/conftest.py`) asserting its count does not grow when more rows are added.
- When the domain needs only a summary of data that grows without bound (meal history,
  ratings), the query filters or aggregates in SQL (`WHERE`, `GROUP BY` with `MAX`, `AVG`,
  `COUNT`) and the domain function accepts that summary; the domain still owns every rule.
