# LedgerLens backend

Python 3.12 project managed with [uv](https://docs.astral.sh/uv/).

```sh
cd backend
uv sync                      # create .venv and install dev tools
uv run ruff check .          # lint
uv run ruff format --check . # formatting
uv run mypy                  # type check (strict)
uv run pytest                # tests
```

## Run the API locally

Without Docker, with the Compose database running (`docker compose up -d db`
from the repo root) and the migrations applied (`make migrate`):

```sh
# from backend/
DATABASE_URL=postgresql://ledgerlens:ledgerlens@localhost:5432/ledgerlens \
DEMOBANK_API_KEY=demo-api-key \
  uv run uvicorn --factory ledgerlens.api.app:create_app --port 8000
curl -i localhost:8000/api/health
```

The server checks its configuration when it starts and exits with an error
when a required setting is missing. `GET /api/health` returns 200
`{"status": "ok", "database": "ok"}`, or 503
`{"status": "degraded", "database": "unavailable"}` when the database does
not answer within 2 seconds. In Docker, the container runs the migrations
itself before it starts uvicorn (`docker-entrypoint.sh`).

## Database

The backend uses PostgreSQL 16 through SQLAlchemy 2 (psycopg 3) and manages
its schema with Alembic migrations in `migrations/`. Everything LedgerLens
owns lives in the `ledgerlens` schema.

```sh
# from the repo root
docker compose up -d db      # start the local database
make migrate                 # apply the migrations (alembic upgrade head)

# from backend/
DATABASE_URL=postgresql://ledgerlens:ledgerlens@localhost:5432/ledgerlens \
  uv run alembic revision --autogenerate -m "add bank accounts"  # new migration
TEST_DATABASE_URL=postgresql://ledgerlens:ledgerlens@localhost:5432/postgres \
  uv run pytest -m db        # the DB tests
```

`make migrate` uses `DATABASE_URL` from your environment, or the Compose db on
`localhost` when it is unset. Alembic reads only `DATABASE_URL`, so migrating
needs no other setting.

`TEST_DATABASE_URL` only names a server: each test run creates its own
database (`ledgerlens_test_<random hex>`) there and drops it afterwards. When
it is unset or blank, the DB tests (the `db` marker, in `tests/db/`) are
skipped.
