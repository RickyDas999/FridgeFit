# FridgeFit

[![CI](https://github.com/RickyDas999/FridgeFit/actions/workflows/ci.yml/badge.svg)](https://github.com/RickyDas999/FridgeFit/actions/workflows/ci.yml)

A personal meal-planning backend that answers one question:

> Given the groceries I currently have, my remaining nutrition goals, food freshness, and meal
> preferences, what should I make?

FridgeFit is a single-user project, built in small reviewed slices with an emphasis on a
codebase that can be explained end to end.

## Status

FridgeFit is a **single-user HTTP API** (FastAPI; SQLite locally, PostgreSQL when deployed) with a
React demo frontend. **Live demo: <https://fridgefit-3f2a.onrender.com>** (public and shared; see
[Deployment](#deployment)). Implemented:

- **Persistence**: SQLAlchemy models for ingredients, inventory batches, recipes, meal history,
  nutrition goals, and meal feedback; the schema is built and evolved by Alembic migrations.
- **Core domain logic**: recipe macros, remaining daily macros, inventory aggregation,
  first-expire-first-out (FEFO) consumption, and atomic meal confirmation.
- **Recommendations**: recipes ranked by availability, freshness, macro fit, and enjoyment, with
  recent eating frequency reported for information.
- **HTTP API**: endpoints to stock the kitchen, add recipes and goals, get recommendations,
  confirm meals (with optional idempotency keys for safe retries), and rate them.
- **Demo frontend**: a dashboard that shows ranked recommendations and why they rank, logs meals,
  handles inventory shortfalls, and rates meals, all through the API.
- **AI meal planning**: "Plan my day" asks Claude to plan the rest of today's meals from the
  existing recipes, under hard limits; FridgeFit checks every plan and falls back to its own
  deterministic planner. See [AI meal planning](#ai-meal-planning).
- **Deployment**: the frontend, API, and PostgreSQL database run on Render, defined in
  `render.yaml`.

Not built yet: authentication and a nutrition-data integration. See
[`docs/current-milestone.md`](docs/current-milestone.md) for exactly what is implemented and what
comes next.

## Getting Started

Requires Python 3.11 or newer.

```bash
git clone https://github.com/RickyDas999/FridgeFit.git
cd FridgeFit
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

Load the demo dataset. This **resets** `fridgefit.db`, builds its tables by running the Alembic
migrations, and fills it with data dated relative to today:

```bash
.venv/bin/python scripts/seed_demo.py
```

The API never creates tables itself. To start from an empty database instead of the demo data,
or to apply a new migration to an existing one, run:

```bash
.venv/bin/alembic upgrade head
```

A `fridgefit.db` created before migrations existed has tables but no migration version, so
`alembic upgrade head` fails on it; re-run the seed script to rebuild it.

The reset only works on SQLite. To add the demo data to any other database without resetting it,
use `--insert-only`, which writes only to a database that is fully migrated and completely
empty:

```bash
.venv/bin/python scripts/seed_demo.py --insert-only
```

Start the API:

```bash
.venv/bin/uvicorn app.api.main:app --reload
```

Then open <http://127.0.0.1:8000/docs> for interactive documentation of every endpoint.

Start the frontend (requires Node.js 20.19+ or 22.12+), in a second terminal:

```bash
cd frontend
npm ci
npm run dev
```

Open <http://localhost:5173> for the dashboard. The header shows **Connected**, or **Offline** if
the API is not running. The frontend calls `http://127.0.0.1:8000` by default; set
`VITE_API_BASE_URL` (for example in `frontend/.env.local`) to point it elsewhere. See [Demo
walkthrough](#demo-walkthrough) for a guided tour.

Run the same checks CI runs:

```bash
.venv/bin/ruff check .
.venv/bin/python -m pytest tests/ -v
```

Each domain module has a matching `tests/test_<module>.py`, and each API route module a
`tests/test_api_<resource>.py`.

Tests use SQLite by default. To run them against PostgreSQL, as CI also does, point
`TEST_DATABASE_URL` at an empty, disposable database (it is wiped before every test):

```bash
TEST_DATABASE_URL=postgresql+psycopg://USER@localhost/fridgefit_test \
  .venv/bin/python -m pytest tests/
```

## Demo walkthrough

A five-minute tour of the full flow. Start from a fresh seed so the numbers match
(`.venv/bin/python scripts/seed_demo.py`), with the API and frontend running as above.

1. **The answer first.** "What to make" ranks every recipe that can be made now; the top pick is
   set large. Every score comes from the backend; the frontend only displays it.
2. **The context.** The sidebar shows calories and macros left today against the goal, what was
   eaten today, and what is in the fridge.
3. **Why it ranks there.** Open the top pick. "Why it ranks here" shows the four parts of the
   score (availability, expiry urgency, macro fit, enjoyment), and "For one serving" shows what
   is needed against what is on hand.
4. **Imperfect matches.** Open "Salmon rice plate": there is no salmon, but a recipe may still be
   suggested when only one main ingredient is missing. It also flags spinach past its use-by
   date, which still counts as on hand: FridgeFit leaves that call to you. "Bean burrito" shows a
   partial amount (80% of the beans needed).
5. **Log a meal.** On the top pick, choose "I ate this", keep 1 serving, and log it. Watch the
   whole page update from the API: fridge quantities drop (the chicken due soonest is used first),
   calories left drop, the ranking refreshes, and the meal appears under "Eaten today".
6. **A shortfall.** Choose "I ate this" again with 20 servings. FridgeFit lists what is short
   instead of logging it, and "Log anyway with what I have" logs only what is in the fridge.
7. **Rate it.** Rate a meal under "Eaten today"; the recipe's enjoyment score updates.
8. **Plan the day.** Under "Plan my day", plan 2 meals. Locally, with no planner configured,
   the plan reads "Planned by FridgeFit's rules"; with one (see [AI meal
   planning](#ai-meal-planning)) it reads "Planned by Claude" with Claude's explanation. Each meal
   shows what it uses and what is left of today afterwards. Follow the plan in order: "I ate
   this" on the first meal logs it and marks it eaten, and the next meal becomes loggable.
   Logging anything the plan did not include (another recipe, or different servings) marks the
   plan out of date.

Worth mentioning under the hood: the backend owns every rule (ranking, availability, FEFO
consumption, serving scaling); each "Log meal" sends an `Idempotency-Key`, so a retried request
can never log a meal twice; and each request runs in its own database transaction, so a failed
write changes nothing. To reset, run the seed script again.

## AI meal planning

`POST /meal-plans` (and "Plan my day" in the dashboard) plans the rest of today's meals: how many
(1–5), an optional prep-time limit, and an optional preference in your own words ("something
light"). Claude is a planning layer on top of FridgeFit's deterministic domain, not a chatbot:

- **Read-only tools.** Claude sees the request, today's remaining macros, the stock, the ranked
  recipes, and a simulation of any sequence of recipes, through three in-process tools. It cannot
  write anything, and it can only choose existing recipes.
- **Hard limits.** At most 6 model calls, 4,096 output tokens per call, and 60 seconds per plan.
- **Deterministic checks.** Every proposed plan is replayed by FridgeFit (unknown or repeated
  recipes, too many meals, the prep limit, eligibility, planning fewer meals than possible).
  Claude gets one chance to fix a rejected plan. Every number shown comes from FridgeFit's own
  simulation; only the explanation is Claude's words.
- **Fallback.** If AI is off, fails, or its plan stays invalid, the response is FridgeFit's own
  greedy plan, with a coarse `fallback_reason`: `ai_disabled`, `ai_failed`, `ai_plan_invalid`,
  or `ai_limit`. The request still succeeds; provider errors, tokens, and cost go only to the
  server log.
- **Cost cap.** The endpoint is public, so `PLANNER_DAILY_LIMIT` caps AI attempts per server
  day (50 in production); past it, plans come from FridgeFit's rules.

With the deployed configuration (`claude-haiku-5-5` at low effort) a plan costs about $0.001
and takes about 5–10 seconds. The evaluation that chose it, comparing three models with
FridgeFit's own planner on seven scenarios, is in
[`docs/current-milestone.md`](docs/current-milestone.md); it found clear gains in two scenarios
and ties or tradeoffs in the rest.

To plan with Claude locally, export a key without it appearing on screen or in shell history,
then start the API with a model:

```bash
read -rs ANTHROPIC_API_KEY && export ANTHROPIC_API_KEY
PLANNER_MODEL=claude-haiku-5-5 .venv/bin/uvicorn app.api.main:app --reload
```

The evaluation harness runs FridgeFit's planner by default (free); `--live` adds Claude
configurations and needs the key, with a spending cap:

```bash
.venv/bin/python scripts/evaluate_planner.py
.venv/bin/python scripts/evaluate_planner.py --live --config claude-haiku-5-5:1 --max-cost-usd 0.05
```

## Deployment

**Live demo: <https://fridgefit-3f2a.onrender.com>** (API docs:
<https://fridgefit-api.onrender.com/docs>). It is a **public, shared demo with no login**: anyone
with the link can log and rate meals. After a period without traffic the free API sleeps, so the
first load can take up to a minute; the dashboard shows **Offline** until then ("Try again").
The free database expires on 2026-11-23 (see [Free-tier limits](#free-tier-limits)).

```text
Browser
  │  HTTPS
  ▼
fridgefit        Render static site: the React build from frontend/, served from a CDN
  │  HTTPS; CORS allows only this site's origin
  ▼
fridgefit-api    Render web service: FastAPI on Uvicorn, Python 3.12
  │  Render's private network (both in Virginia)
  ▼
fridgefit-db     Render PostgreSQL 16: outlives API restarts and redeploys
```

Locally nothing changes: with no `DATABASE_URL`, the API, migrations, and seed script use the
SQLite file `fridgefit.db`, and the tests use SQLite unless `TEST_DATABASE_URL` is set.

### Configuration

Everything is declared in [`render.yaml`](render.yaml), a Render Blueprint. No secrets are
committed: Render links `DATABASE_URL` from the database itself, and `ANTHROPIC_API_KEY` is
entered in the Render dashboard.

| Variable | Service | Purpose |
|---|---|---|
| `DATABASE_URL` | API | The database. Unset locally means `sqlite:///fridgefit.db`; a `postgres://` or `postgresql://` URL is pointed at the psycopg 3 driver. |
| `FRONTEND_ORIGIN` | API | The one browser origin CORS allows. Unset locally means the Vite dev origins; `*` is refused at startup. |
| `TZ` | API | `America/New_York`. Stored times and "today" are the user's local time; Render's clock is UTC. |
| `PORT` | API | Set by Render; Uvicorn binds to it. |
| `PYTHON_VERSION` | API | `3.12`, as tested in CI. |
| `PLANNER_MODEL` | API | `claude-haiku-5-5`. The Claude model for meal planning; unset means AI planning is off. |
| `PLANNER_EFFORT` | API | `low` (the default). One of `low`, `medium`, `high`, `xhigh`, `max`; anything else stops startup. |
| `PLANNER_DAILY_LIMIT` | API | `50`. AI planning attempts per server day; unset means no limit, `0` turns AI planning off. |
| `ANTHROPIC_API_KEY` | API | Secret, set only in the Render dashboard (`sync: false`). Unset means AI planning is off. |
| `VITE_API_BASE_URL` | Static site | The API's URL, baked into the JavaScript at build time (public). |
| `NODE_VERSION` | Static site | `22`, as in CI. |

### How a change reaches production

1. A pull request merges into `main`, which only happens when CI passes.
2. Both services auto-deploy only after CI passes on that commit ("After CI Checks Pass").
3. The API builds with `pip install .` and starts with
   `alembic upgrade head && uvicorn app.api.main:app --host 0.0.0.0 --port $PORT`. Migrations run
   first and are a no-op when the database is current; a failing migration stops the API from
   starting. Render marks the deploy live only once `/health` returns 200.
4. The static site builds with `npm ci && npm run build` and publishes `frontend/dist`.

A schema change is a model edit plus a reviewed migration
(`.venv/bin/alembic revision --autogenerate -m "..."`, then read and fix the generated file).
`tests/test_migrations.py` fails if the models and migrations disagree. Production applies the
migration on the next deploy.

### Demo data in production

Loaded once, from a developer machine, with the database's **External Database URL** (Render
dashboard → `fridgefit-db` → Connect). Keep the URL out of files and shell history: type the
first line, copy the URL in Render *last*, then press Enter, so `pbpaste` reads the URL.

```bash
DB_URL=$(pbpaste)
DATABASE_URL="$DB_URL" .venv/bin/python scripts/seed_demo.py --insert-only
unset DB_URL
```

`--insert-only` writes only to a database at the latest migration with every table empty, and
names the database it checked when it refuses. The default reset refuses anything but SQLite, so
it cannot wipe production.

### Health, failures, and restarts

Verified on Render, or locally against PostgreSQL where noted:

- `/health` runs `SELECT 1`: 200 only when the API can reach the database. Render's health check
  uses it.
- Database unreachable (locally): `/health` and data endpoints return 500, and the logs show the
  `OperationalError`. Once the database is back, requests succeed without restarting the API.
- Database restarted between requests (locally): no request fails; pooled connections are checked
  before use (`pool_pre_ping`) and replaced if dead.
- API restart or redeploy (Render): data persists, and no migration re-runs.
- Render's Logs tab for `fridgefit-api` shows the build, migrations, startup, every request line,
  and full tracebacks for errors.

### Free-tier limits

- The API sleeps after a period without traffic; the next request waits while it wakes. The
  static site does not sleep.
- The free database (created 2026-10-24) expires on **2026-11-23** and is deleted 14 days later.
  It has no backups. The planned rebuild after it is gone (not yet exercised): create a new
  database from the Blueprint, redeploy the API (its start command migrates the new database),
  then load the demo data again with `--insert-only`.
- There is no authentication: the demo's data is shared by everyone who opens it.

## API

| Endpoint | Purpose |
|---|---|
| `GET /health` | API and database are up |
| `POST /ingredients`, `GET /ingredients` | Nutrition reference data |
| `POST /inventory/batches`, `GET /inventory` | Record groceries; see what's on hand |
| `POST /recipes`, `GET /recipes`, `GET /recipes/{recipe_id}` | Recipes with derived macros |
| `POST /nutrition-goals`, `GET /nutrition-state?as_of=` | Daily targets and what's left today |
| `GET /recommendations?as_of=` | What to make, ranked, with the reasons |
| `POST /recipes/{recipe_id}/confirm` | Log a meal and consume its ingredients; send an `Idempotency-Key` header to make retries safe |
| `GET /meal-logs?consumed_on=` | Meals eaten on a day |
| `POST /meal-logs/{meal_log_id}/feedback` | Rate a meal 1–5 |
| `POST /meal-plans` | Plan the rest of today's meals with Claude, or FridgeFit's planner as the fallback; writes nothing |

Dates are `YYYY-MM-DD` and default to today; datetimes are local time without a timezone.

## Project Layout

```text
alembic/            database migrations (alembic.ini configures them)
render.yaml         Render Blueprint: static site, API web service, PostgreSQL database
app/
├── errors.py       shared InvalidInputError
├── persistence/    database setup, enums, SQLAlchemy models
├── domain/         deterministic business logic and input validation
├── application/    thin workflows combining persistence and domain logic; the AI planner
├── evaluation/     planner evaluation: scenarios, metrics, price estimates
└── api/            FastAPI app, routes, and request/response schemas
frontend/           React + TypeScript + Vite UI (talks to the API over HTTP)
tests/              pytest suite, run against SQLite (or PostgreSQL via TEST_DATABASE_URL)
scripts/            developer and CI tooling (demo seed, planner evaluation, AI review helper)
docs/               architecture, domain rules, and current status
```

## Documentation

| Document | What it covers |
|---|---|
| [`docs/architecture.md`](docs/architecture.md) | Stack, infrastructure limits, layering, API and transaction rules, persistence conventions |
| [`docs/domain-rules.md`](docs/domain-rules.md) | Product rules: inventory, recipes, meal history, goals, recommendation scoring |
| [`docs/current-milestone.md`](docs/current-milestone.md) | What is implemented, what is not, and what is next |
| [`CLAUDE.md`](CLAUDE.md) | How the AI implementation assistant works in this repository |
| [`AGENTS.md`](AGENTS.md) | The contract for the AI pull-request reviewer |

## Development Workflow

- Changes go through feature branches and pull requests into `main`, using the
  [pull request template](.github/pull_request_template.md).
- **CI** runs Ruff and pytest on Python 3.11 and 3.12, pytest again against PostgreSQL 16, and a
  frontend type-check and build, for every pull request. All four must pass to merge.
- **AI review** is optional and advisory. Adding the `ai-review` label to a pull request runs a
  Claude review that posts one structured review comment, typically costing about a cent. A
  malformed response gets at most two short repair requests. It never blocks merging; its findings are hypotheses for the developer to accept or
  reject. To preview a pull request's review size without calling the API:

  ```bash
  .venv/bin/python scripts/ai_review.py --pr <number> --dry-run
  ```
