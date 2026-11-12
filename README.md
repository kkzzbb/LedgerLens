# LedgerLens

LedgerLens syncs a business bank account from DemoBank, shows spending by
category (the Overview and Expenses pages), and flags two kinds of potential
issues for a person to review: possible duplicate payments (#28) and
unusually large expenses (#30). DemoBank is a simulated bank with fictional
data: no real bank is connected. A flag is a potential issue, never a
finding of fraud.

See `docs/scope.md` for what is built. The backend lives in `backend/`, the
simulated bank DemoBank in `demobank/`, the frontend in `frontend/`, and the
design docs in `docs/`.

## Quick start

Prerequisite: Docker with Compose v2.

From the repo root:

```sh
cp .env.example .env     # demo values; .env is ignored by git
docker compose up --build
```

This starts 4 services:

| Service | What it is | URL |
| --- | --- | --- |
| `frontend` | the UI (Vite dev server) | http://localhost:5173 |
| `backend` | the API | http://localhost:8000 (health: `/api/health`, API docs: `/docs`) |
| `demobank` | a simulated bank with fictional data | http://localhost:8100 |
| `db` | PostgreSQL | localhost:5432 |

`frontend` starts once the backend is healthy. The browser talks only to
port 5173: the dev server forwards `/api/...` to the backend.

When the backend container starts, it checks its configuration, applies the
database migrations (`alembic upgrade head`) and then serves the API. It
does not start when the configuration is invalid or a migration cannot run.

## Demo walkthrough

Open http://localhost:5173, then:

1. **Sync now** on the Overview: fetches DemoBank's accounts and
   transactions, categorizes them and runs the anomaly rules
2. Overview: account balances, money in and out per month, and the recent
   transactions
3. Transactions: every synced transaction, newest first, with a search
4. Expenses: spending per category and month
5. Alerts: the 2 planted flags, a possible duplicate payment and an
   unusually large expense
6. **Mark reviewed** on a flag: the flag is marked as reviewed

The 2 flags come from DemoBank, which plants one duplicate payment and one
unusually large expense at the end of its history (#12, see
[`demobank/README.md`](demobank/README.md) "Planted anomalies"). Syncing
again adds no duplicate transactions and no duplicate flags.

The data lives in a Docker volume, so `docker compose down` then
`docker compose up` keeps it. `docker compose down -v` followed by
`docker compose up --build` resets the data and the flags: DemoBank
generates a new history anchored on that day, and the next sync flags the
planted anomalies again.

## API

One line per route; `http://localhost:8000/docs` has the request and
response shapes.

- `GET /api/health` - the API and its database are up (200) or the
  database does not answer (503)
- `POST /api/sync` - sync every account from DemoBank, then run the
  anomaly rules
- `GET /api/accounts` - the synced accounts with their balances
- `GET /api/transactions` - the synced transactions, newest first
- `GET /api/categories` - the fixed category list
- `GET /api/reports/monthly?from=YYYY-MM&to=YYYY-MM` - money in, money out
  and net per month
- `GET /api/reports/expenses?from=YYYY-MM&to=YYYY-MM` - debits per expense
  category and month
- `GET /api/anomalies` - the potential issues flagged for review
- `POST /api/anomalies/{id}/review` - mark a flag as reviewed

A sync can also run from the command line, from `backend/` (it needs the
same settings as the API: `DATABASE_URL`, `DEMOBANK_API_KEY`, and
`DEMOBANK_BASE_URL` when DemoBank is not at `http://demobank:8100`):

```sh
uv run python -m ledgerlens.sync
```

## Project layout

- `backend/` - the LedgerLens API (FastAPI), see
  [`backend/README.md`](backend/README.md)
  - `ledgerlens/api/` - the HTTP routes
  - `ledgerlens/services/` - use cases, such as the sync
  - `ledgerlens/domain/` - pure rules: categories, anomaly rules, reports,
    money
  - `ledgerlens/db/` - SQLAlchemy models, repositories and the session
    (migrations in `migrations/`)
  - `ledgerlens/connectors/` - the bank connector for DemoBank
- `demobank/` - the simulated bank, see
  [`demobank/README.md`](demobank/README.md)
- `frontend/` - the UI (React, Vite)
- `docs/` - scope, accounting rules and process
- `docker-compose.yml` - the 4 local services
- `Makefile` - install, lint, type check, test and migrate

## Running the checks

Prerequisites: GNU make, [uv](https://docs.astral.sh/uv/) and Node 22.

From the repo root:

```sh
make install   # uv sync in backend/ and demobank/, npm ci in frontend/
make test      # lint, format check, type check and tests for backend, DemoBank and frontend
```

Run `make install` before `make test`, and again whenever the dependencies
change. `make test` stops at the first check that fails. `make help` lists
every target.

The DB tests need PostgreSQL. Start the Compose database and apply the
migrations from the repo root, then run the tests from `backend/`:

```sh
docker compose up -d db
make migrate     # apply the migrations (DATABASE_URL, default: the Compose db)

# from backend/
TEST_DATABASE_URL=postgresql://ledgerlens:ledgerlens@localhost:5432/postgres uv run pytest -m db
```

## Documents

- [`docs/scope.md`](docs/scope.md) - what is built, and what is not
- [`docs/accounting-rules.md`](docs/accounting-rules.md) - the financial
  conventions, categories, anomaly rules and reports
- [`AGENTS.md`](AGENTS.md) - commands and rules for coding agents
- [`backend/README.md`](backend/README.md) - the backend, its database and
  migrations
- [`demobank/README.md`](demobank/README.md) - the simulated bank and its
  data
