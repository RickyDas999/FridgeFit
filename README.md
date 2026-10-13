# FridgeFit

[![CI](https://github.com/RickyDas999/FridgeFit/actions/workflows/ci.yml/badge.svg)](https://github.com/RickyDas999/FridgeFit/actions/workflows/ci.yml)

A personal meal-planning backend that answers one question:

> Given the groceries I currently have, my remaining nutrition goals, food freshness, and meal
> preferences, what should I make?

FridgeFit is a single-user project, built in small reviewed slices with an emphasis on a
codebase that can be explained end to end.

## Status

FridgeFit is a **single-user HTTP API** (FastAPI, SQLite) with the foundation of a React
frontend. Implemented:

- **Persistence**: SQLAlchemy models for ingredients, inventory batches, recipes, meal history,
  nutrition goals, and meal feedback, on SQLite.
- **Core domain logic**: recipe macros, remaining daily macros, inventory aggregation,
  first-expire-first-out (FEFO) consumption, and atomic meal confirmation.
- **Recommendations**: recipes ranked by availability, freshness, macro fit, and enjoyment, with
  recent eating frequency reported for information.
- **HTTP API**: endpoints to stock the kitchen, add recipes and goals, get recommendations,
  confirm meals (with optional idempotency keys for safe retries), and rate them.

Not built yet: rating meals in the frontend, authentication, nutrition-data and Claude
integrations, and migrations. See [`docs/current-milestone.md`](docs/current-milestone.md) for
exactly what is implemented and what comes next.

## Getting Started

Requires Python 3.11 or newer.

```bash
git clone https://github.com/RickyDas999/FridgeFit.git
cd FridgeFit
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

Load the demo dataset (this **resets** `fridgefit.db`; dates are relative to today):

```bash
.venv/bin/python scripts/seed_demo.py
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

Open <http://localhost:5173> for the dashboard: ranked recommendations (click one to see why it
ranked there, or log it as a meal with "I ate this"), today's nutrition, today's meals, and
inventory. The header shows **Backend connected**, or **Backend unavailable** if the API is not
running. The frontend calls `http://127.0.0.1:8000` by default; set `VITE_API_BASE_URL` (for
example in `frontend/.env.local`) to point it elsewhere.

Run the same checks CI runs:

```bash
.venv/bin/ruff check .
.venv/bin/python -m pytest tests/ -v
```

Each domain module has a matching `tests/test_<module>.py`, and each API route module a
`tests/test_api_<resource>.py`.

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

Dates are `YYYY-MM-DD` and default to today; datetimes are local time without a timezone.

## Project Layout

```text
app/
├── errors.py       shared InvalidInputError
├── persistence/    database setup, enums, SQLAlchemy models
├── domain/         deterministic business logic and input validation
├── application/    thin workflows combining persistence and domain logic
└── api/            FastAPI app, routes, and request/response schemas
frontend/           React + TypeScript + Vite UI (talks to the API over HTTP)
tests/              pytest suite, run against an in-memory SQLite database
scripts/            developer and CI tooling (demo seed, AI review helper)
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
- **CI** runs Ruff and pytest on Python 3.11 and 3.12, and a frontend type-check and build, for
  every pull request. The Python checks must pass to merge.
- **AI review** is optional and advisory. Adding the `ai-review` label to a pull request runs a
  Claude review that posts one structured review comment, typically costing about a cent. A
  malformed response gets at most two short repair requests. It never blocks merging; its findings are hypotheses for the developer to accept or
  reject. To preview a pull request's review size without calling the API:

  ```bash
  .venv/bin/python scripts/ai_review.py --pr <number> --dry-run
  ```
