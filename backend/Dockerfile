# LedgerLens backend image. Built by `docker compose up --build` from the
# repo root. Installs the runtime dependencies from uv.lock only: no dev tools
# and no tests in the image.

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

# uv is mounted for the install steps only and does not stay in the image.
# A uv.lock that no longer matches pyproject.toml fails the build here.
COPY pyproject.toml uv.lock README.md ./
RUN --mount=from=ghcr.io/astral-sh/uv:0.11.23,source=/uv,target=/usr/local/bin/uv \
    uv lock --check \
    && uv sync --frozen --no-dev --no-install-project

COPY alembic.ini docker-entrypoint.sh ./
COPY migrations ./migrations
COPY ledgerlens ./ledgerlens
RUN --mount=from=ghcr.io/astral-sh/uv:0.11.23,source=/uv,target=/usr/local/bin/uv \
    uv sync --frozen --no-dev --no-editable

RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin ledgerlens
USER 10001

ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000

# Checks the configuration, applies the migrations, then starts uvicorn.
CMD ["/app/docker-entrypoint.sh"]
