# LedgerLens

Bank sync and analysis: LedgerLens syncs a business bank account from a
simulated bank and shows spending by category and flags anomalies
(possible duplicate payments, unusually large expenses). See
`docs/scope.md`. The backend lives in `backend/`, the
simulated bank DemoBank in `demobank/`, the frontend in `frontend/`, and the
design docs in `docs/`.

## Run with Docker

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

Demo: open http://localhost:5173 and click "Sync now" on the Overview. The
account cards and recent transactions fill with DemoBank's data. Before the
first sync the Overview shows its empty state.

The data lives in a Docker volume, so `docker compose down` then
`docker compose up` keeps it, and syncing again adds no duplicates.
`docker compose down -v` deletes all data. On the next start DemoBank
generates a new history anchored on that day, so the planted anomalies move
with it.

When the
backend container starts, it checks its configuration, applies the database
migrations (`alembic upgrade head`) and then serves the API. It does not
start when the configuration is invalid or a migration cannot run.

Health check: `http://localhost:8000/api/health`

- `200` with `{"status":"ok","database":"ok"}`: the API is up and its
  database answers
- `503` with `{"status":"degraded","database":"unavailable"}`: the API is up
  but its database does not answer within 2 seconds

`docker compose ps` shows the backend as `healthy` once the API answers 200.

DemoBank health check: `http://localhost:8100/health` returns `200` with
`{"status":"ok"}` (no key needed). Every `/v1/*` route needs the
`X-API-Key` header with `DEMOBANK_API_KEY` from `.env`:

```sh
curl -i -H "X-API-Key: demo-api-key" localhost:8100/v1/ping   # 200 {"status":"ok"}
curl -i localhost:8100/v1/ping                                # 401 {"error":"unauthorized"}
```

`docker compose ps` shows `demobank` as `healthy` once `/health` answers 200.

## Running the checks

Prerequisites: GNU make, [uv](https://docs.astral.sh/uv/) and Node 22.

From the repo root:

```sh
make install   # uv sync in backend/ and demobank/, npm ci in frontend/
make test      # lint, format check, type check and tests for backend, DemoBank and frontend
```

Run `make install` before `make test`, and again whenever the dependencies
change. Without it the frontend checks fail, because `frontend/node_modules`
is missing. `make test` stops at the first check that fails.

`make help` lists every target.
