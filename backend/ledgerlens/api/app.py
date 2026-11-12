"""The FastAPI application.

`create_app()` reads no settings and opens no connection. The settings are
checked when the application starts (its lifespan), so a server started with
a missing or invalid configuration exits at once instead of serving requests
that fail later:

    uv run uvicorn --factory ledgerlens.api.app:create_app
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from ledgerlens.api import health
from ledgerlens.config import ConfigError, get_settings


class StartupError(RuntimeError):
    """The application cannot start. The message never holds a setting's value."""


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Checks the configuration before the first request is served."""
    try:
        get_settings()
    except ConfigError as exc:
        message = f"Invalid configuration:\n{exc}"
    else:
        yield
        return
    # Raised outside the `except` block so the ConfigError is not chained.
    # Uvicorn logs it and exits with a non-zero status.
    raise StartupError(message)


def create_app() -> FastAPI:
    """The LedgerLens API application."""
    app = FastAPI(title="LedgerLens", lifespan=lifespan)
    app.include_router(health.router)
    return app
