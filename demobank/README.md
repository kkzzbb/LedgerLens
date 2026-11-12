# DemoBank

DemoBank is a simulated bank: a small HTTP API that serves fictional data so
LedgerLens can be demonstrated without a real bank. No real account, person
or transaction is behind it.

It is a separate Python 3.12 project managed with
[uv](https://docs.astral.sh/uv/), and it imports nothing from the LedgerLens
backend (`ledgerlens`).

## Install and check

```sh
cd demobank
uv sync                      # create .venv and install dev tools
uv run ruff check .          # lint
uv run ruff format --check . # formatting
uv run mypy                  # type check (strict)
uv run pytest                # tests (no database, no Docker)
```

The root `make install` and `make test` run the same steps.

## Settings

Read from the process environment only (no `.env` file). An empty or blank
value counts as unset.

| Variable | Default | Meaning |
| --- | --- | --- |
| `DEMOBANK_API_KEY` | required | The key every `/v1/*` request must send in `X-API-Key` |
| `DEMOBANK_ADMIN_ENABLED` | `false` | Turns the admin scenario routes on (#12): `true`, `false`, `1` or `0` |
| `DEMOBANK_ADMIN_KEY` | empty | The admin key (#12). Required, and different from `DEMOBANK_API_KEY`, when admin is enabled |

`uv run python -m demobank.config` prints `Configuration OK`, or one line
per problem on stderr with exit status 1. No line contains a value.

## Run without Docker

```sh
# from demobank/
DEMOBANK_API_KEY=demo-api-key uv run uvicorn --factory demobank.app:create_app --port 8100
```

The server checks its settings when it starts and exits with an error when
one is missing or invalid. Then:

```sh
curl -i localhost:8100/health                                 # 200 {"status":"ok"}
curl -i localhost:8100/v1/ping                                # 401 {"error":"unauthorized"}
curl -i -H "X-API-Key: demo-api-key" localhost:8100/v1/ping   # 200 {"status":"ok"}
```

- `GET /health` is public and only says the process is up. It touches no
  database
- Every `/v1/*` route needs the `X-API-Key` header. A missing, empty or
  wrong key gets 401 `{"error":"unauthorized"}`, the same body in every case
- `/docs` and `/openapi.json` are public

With Docker, `docker compose up --build` from the repo root starts DemoBank
on port 8100 next to the backend (see the root `README.md`).
