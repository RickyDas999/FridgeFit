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
- SQLite as the V1 relational database
- FastAPI for the V1 HTTP API
- Pydantic for HTTP request and response schemas
- React + TypeScript + Vite for the demo frontend (a Node.js toolchain confined to `frontend/`)
- pytest
- Ruff for linting, pinned to an exact version and configured in `pyproject.toml`
- GitHub Actions for CI: lint and tests on every pull request and every push to `main`
- An advisory Claude review in GitHub Actions, run on request by labeling a pull request
  `ai-review`: one review request, plus at most two bounded format-repair requests. AI review
  never blocks merging and never writes code; its findings are hypotheses for the developer.

PostgreSQL is a possible future migration only if multi-user deployment or concurrency genuinely
requires it.

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
- FastAPI may enable CORS only as narrowly as the local Vite-to-FastAPI development setup
  requires (the Vite dev origin). Broader CORS belongs to a deployment decision.
- Deployment is out of scope until a separate milestone decides it.

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

- SQLite foreign-key enforcement is enabled on every connection (`PRAGMA foreign_keys=ON` via a
  SQLAlchemy connect-event hook). SQLite leaves foreign keys unenforced by default.
- Clearly invalid values (negative quantities or macros, ratings outside 1–5, non-positive
  servings) are rejected by database `CheckConstraint`s.
- Rules a database constraint cannot express are enforced before each save with a SQLAlchemy
  `before_flush` hook in `models.py`. The current one rejects a Recipe with no ingredients, which
  a constraint cannot check because the Recipe row must exist before its ingredient rows.
- Recipe instructions are stored in a JSON column.
- There are no migrations (Alembic is not set up). The test fixture and the API's startup
  (lifespan) create missing tables with `Base.metadata.create_all`. This never alters existing
  tables, so a schema change to an existing database needs the database recreated until
  migrations exist.
- Queries that load a list eager-load the relationships the code reads (`selectinload`), so a
  list endpoint runs a fixed number of queries however many rows exist; lazy loading one query
  per row (N+1) is not acceptable on list paths. Single-item paths, whose cost is bounded by
  one row, may load lazily.
- Each list endpoint has a query-count test (the `count_queries` fixture in
  `tests/conftest.py`) asserting its count does not grow when more rows are added.
- When the domain needs only a summary of data that grows without bound (meal history,
  ratings), the query filters or aggregates in SQL (`WHERE`, `GROUP BY` with `MAX`, `AVG`,
  `COUNT`) and the domain function accepts that summary; the domain still owns every rule.
