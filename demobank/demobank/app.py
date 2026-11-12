"""The FastAPI application.

`create_app()` reads no settings. The settings are checked when the
application starts (its lifespan), then the database step runs: it creates
the `demobank_sim` schema and generates the history on first start (#9). A
server started with a missing or invalid configuration, or without a
reachable database, exits at once instead of serving requests that fail
later:

    uv run uvicorn --factory demobank.app:create_app --port 8100
"""

import logging
import sys
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

from fastapi import FastAPI

from demobank.api import health, v1
from demobank.api.auth import UnauthorizedError, unauthorized_handler
from demobank.config import ConfigError, Settings, get_settings
from demobank.db.startup import DatabaseStartupError, make_engine, prepare_database

# The database step of the startup. It raises `DatabaseStartupError` (one line,
# without the URL) when the database cannot be prepared.
DatabaseStep = Callable[[Settings], object]

# DemoBank's own log lines, next to uvicorn's (uvicorn only configures its own loggers).
_log_handler = logging.StreamHandler(sys.stderr)
_log_handler.setFormatter(logging.Formatter("%(levelname)-9s %(name)s: %(message)s"))


class StartupError(RuntimeError):
    """The application cannot start. The message never holds a setting's value."""


def _configure_logging() -> None:
    logger = logging.getLogger("demobank")
    logger.setLevel(logging.INFO)
    if _log_handler not in logger.handlers:
        logger.addHandler(_log_handler)


def _lifespan(
    database_step: DatabaseStep,
) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        """Checks the configuration, then prepares the database, before the first request."""
        _configure_logging()
        try:
            settings = get_settings()
        except ConfigError as exc:
            message = f"Invalid configuration:\n{exc}"
        else:
            try:
                database_step(settings)
            except DatabaseStartupError as exc:
                message = str(exc)
            else:
                # One engine for the request-time queries (#10), disposed on shutdown.
                app.state.engine = make_engine(settings.demobank_database_url.get_secret_value())
                try:
                    yield
                finally:
                    app.state.engine.dispose()
                return
        # Raised outside the `except` blocks so the cause is not chained.
        # Uvicorn logs it and exits with a non-zero status.
        raise StartupError(message)

    return lifespan


def create_app(*, database_step: DatabaseStep | None = None) -> FastAPI:
    """The DemoBank API application.

    `database_step` replaces the database step of the startup (the unit
    tests pass a no-op, so they need no database).
    """
    step = database_step if database_step is not None else prepare_database
    app = FastAPI(title="DemoBank", lifespan=_lifespan(step))
    app.add_exception_handler(UnauthorizedError, unauthorized_handler)
    app.include_router(health.router)
    app.include_router(v1.router)
    return app
