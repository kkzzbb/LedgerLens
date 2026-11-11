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

Rules

- Dependencies are added in `backend/pyproject.toml` with `uv add`. Do not
  add one without asking
- Money is always `Decimal`, never `float`
- `ledgerlens/domain/` stays pure: no I/O and no framework imports
- Lint, format, type check and tests must pass before a commit
