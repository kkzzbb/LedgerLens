# LedgerLens root Makefile (GNU make). Run from the repo root.
#
# Every recipe cds into its subproject, so the caller's working directory
# does not matter. A new package or test suite extends these targets.
# A target shows up in `make help` through the `## description` after its name.

.DEFAULT_GOAL := help

# Steps run one after another and in the written order, even under `make -j`.
.NOTPARALLEL:

.PHONY: help install lint typecheck test migrate

# Database `make migrate` uses when DATABASE_URL is unset or blank: the Compose
# db seen from the host, with the demo credentials.
LOCAL_DATABASE_URL := postgresql://ledgerlens:ledgerlens@localhost:5432/ledgerlens

help: ## List the targets
	@awk 'BEGIN { FS = ":.*## " } /^[a-zA-Z_-]+:.*## / { printf "  make %-10s %s\n", $$1, $$2 }' $(MAKEFILE_LIST)

install: ## Install backend and frontend dependencies (uv sync, npm ci)
	cd backend && uv sync
	cd frontend && npm ci

lint: ## Lint and format check, report only (ruff check, ruff format --check, eslint)
	cd backend && uv run ruff check .
	cd backend && uv run ruff format --check .
	cd frontend && npm run lint

typecheck: ## Type check (mypy, tsc)
	cd backend && uv run mypy
	cd frontend && npm run typecheck

test: lint typecheck ## Run every check: lint, typecheck, then pytest and the frontend tests
	cd backend && uv run pytest
	cd frontend && npm test

migrate: ## Apply the database migrations (DATABASE_URL, default: the local Compose db)
	cd backend && DATABASE_URL="$${DATABASE_URL:-$(LOCAL_DATABASE_URL)}" uv run alembic upgrade head
