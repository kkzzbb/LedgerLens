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
