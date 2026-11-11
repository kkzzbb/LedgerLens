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
