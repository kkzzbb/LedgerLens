"""The FastAPI application.

`create_app()` reads no settings and opens no connection. The settings are
checked when the application starts (its lifespan), so a server started with
a missing or invalid configuration exits at once instead of serving requests
that fail later:

    uv run uvicorn --factory ledgerlens.api.app:create_app
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from ledgerlens.api import accounts, anomalies, health, reports, sync, transactions
from ledgerlens.config import ConfigError, get_settings


class StripQueryString(logging.Filter):
    """Drops the query string from uvicorn access log records.

    Query parameters may hold transaction contents (the `q` search text),
    which must not be logged. Uvicorn's access record `args` are
    `(client_addr, method, full_path, http_version, status_code)`.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3 and isinstance(args[2], str):
            record.args = (*args[:2], args[2].split("?", 1)[0], *args[3:])
        return True


def strip_access_log_query_strings() -> None:
    """Attaches `StripQueryString` to the `uvicorn.access` logger, once."""
    logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(existing, StripQueryString) for existing in logger.filters):
        logger.addFilter(StripQueryString())


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
    strip_access_log_query_strings()
    app = FastAPI(title="LedgerLens", lifespan=lifespan)
    app.include_router(health.router)
    app.include_router(accounts.router)
    app.include_router(sync.router)
    app.include_router(transactions.router)
    app.include_router(reports.router)
    app.include_router(anomalies.router)
    return app
