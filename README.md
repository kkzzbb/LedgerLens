# LedgerLens

Bank sync, accounting and analysis. The backend lives in `backend/`, the
frontend in `frontend/`, and the design docs in `docs/`.

## Run with Docker

Prerequisite: Docker with Compose v2.

From the repo root:

```sh
cp .env.example .env     # demo values; .env is ignored by git
docker compose up --build
```

This starts PostgreSQL (`db`) and the backend API on port 8000. When the
backend container starts, it checks its configuration, applies the database
migrations (`alembic upgrade head`) and then serves the API. It does not
start when the configuration is invalid or a migration cannot run.

Health check: `http://localhost:8000/api/health`

- `200` with `{"status":"ok","database":"ok"}`: the API is up and its
  database answers
- `503` with `{"status":"degraded","database":"unavailable"}`: the API is up
  but its database does not answer within 2 seconds

`docker compose ps` shows the backend as `healthy` once the API answers 200.

## Running the checks

Prerequisites: GNU make, [uv](https://docs.astral.sh/uv/) and Node 22.

From the repo root:

```sh
make install   # uv sync in backend/, npm ci in frontend/
make test      # lint, format check, type check and tests for backend and frontend
```

Run `make install` before `make test`, and again whenever the dependencies
change. Without it the frontend checks fail, because `frontend/node_modules`
is missing. `make test` stops at the first check that fails.

`make help` lists every target.
