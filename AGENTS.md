# AGENTS.md

LedgerLens backend and DemoBank (Python 3.12, managed with uv) and frontend
(React, TypeScript, npm). Design docs live in `docs/`.

Documents

- `docs/process.md` - how work is organized
- `docs/scope.md` - what is built (and what is not) and in which order
- `docs/accounting-rules.md` - money, categories, anomaly rules and reports

Commands

Run from the repo root:

- `make install` - install backend, DemoBank and frontend dependencies
- `make lint` - lint and format check, backend, DemoBank and frontend
  (reports only)
- `make typecheck` - type check, backend, DemoBank and frontend
- `make test` - lint, format check, type check and every test suite
- `docker compose up --build` - build and start PostgreSQL, the backend
  API (port 8000), DemoBank (port 8100) and the frontend (port 5173;
  needs `.env`, copied from `.env.example`)
- `docker compose up -d db` - start the local PostgreSQL 16
- `make migrate` - apply the migrations (`DATABASE_URL`, default: the
  Compose db on `localhost`)

Run from `backend/`:

- `uv sync` - install dependencies
- `uv run pytest` - the whole suite
- `uv run pytest tests/unit/test_package.py` - one test file
- `uv run ruff check .` - lint
- `uv run ruff format .` - format
- `uv run mypy` - type check (strict)
- `TEST_DATABASE_URL=postgresql://ledgerlens:ledgerlens@localhost:5432/postgres uv run pytest -m db`
  - the DB tests (skipped when `TEST_DATABASE_URL` is unset)
- `uv run alembic revision --autogenerate -m "..."` - create a new migration
  (needs `DATABASE_URL` and a migrated database)

Run from `demobank/`:

- `uv sync` - install dependencies
- `uv run pytest` - the whole suite
- `uv run pytest tests/unit/test_app.py` - one test file
- `uv run ruff check .` - lint
- `uv run ruff format .` - format
- `uv run mypy` - type check (strict)
- `DEMOBANK_API_KEY=demo-api-key DEMOBANK_DATABASE_URL=postgresql://ledgerlens:ledgerlens@localhost:5432/ledgerlens uv run uvicorn --factory demobank.app:create_app --port 8100`
  - run DemoBank without Docker (needs `docker compose up -d db`)

Run from `frontend/`:

- `npm ci` - install dependencies
- `npm run dev` - dev server on port 5173
- `npm run lint` - lint
- `npm run typecheck` - type check (strict)
- `npm test` - the whole suite
- `npm run build` - production build

Rules

- Dependencies are added in `backend/pyproject.toml` or
  `demobank/pyproject.toml` with `uv add`. Do not add one without asking
- Money is always `Decimal`, never `float`
- `ledgerlens/domain/` stays pure: no I/O and no framework imports
- Lint, format, type check and tests must pass before a commit: run
  `make test` from the repo root
