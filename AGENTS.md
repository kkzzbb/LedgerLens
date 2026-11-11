# AGENTS.md

LedgerLens backend: Python 3.12, managed with uv. Design docs live in `docs/`.

Documents

- `docs/process.md` - how work is organized

Commands

Run from `backend/`:

- `uv sync` - install dependencies
- `uv run pytest` - the whole suite
- `uv run pytest tests/unit/test_package.py` - one test file
- `uv run ruff check .` - lint
- `uv run ruff format .` - format
- `uv run mypy` - type check (strict)

Run from `frontend/`:

- `npm ci` - install dependencies
- `npm run dev` - dev server on port 5173
- `npm run lint` - lint
- `npm run typecheck` - type check (strict)
- `npm test` - the whole suite
- `npm run build` - production build

Rules

- Dependencies are added in `backend/pyproject.toml` with `uv add`. Do not
  add one without asking
- Money is always `Decimal`, never `float`
- `ledgerlens/domain/` stays pure: no I/O and no framework imports
- Lint, format, type check and tests must pass before a commit
