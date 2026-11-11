# LedgerLens

Bank sync, accounting and analysis. The backend lives in `backend/`, the
frontend in `frontend/`, and the design docs in `docs/`.

## Running the checks

Prerequisites: GNU make, [uv](https://docs.astral.sh/uv/) and Node 22.

From the repo root:

```sh
make install   # uv sync in backend/, npm ci in frontend/
make test      # lint, format check, type check and tests for backend and frontend
```

`make test` does not install dependencies, so run `make install` first, and
again whenever the dependencies change. It stops at the first check that fails.

`make help` lists every target.
