"""Health checks: is the application database reachable?

A check runs in its own daemon thread and gets an overall deadline, so a
database that does not answer can never make the caller hang. A check that
misses the deadline is abandoned; it ends on its own once the driver's
connect timeout (`make_engine`) runs out.

A failed check logs one `WARNING` line with the exception class name only:
never the message, which may hold connection details.
"""

import logging
import threading
from collections.abc import Callable

from sqlalchemy import Engine, text

HEALTH_DEADLINE_SECONDS = 2.0

logger = logging.getLogger(__name__)

DatabaseCheck = Callable[[], bool]
"""A check that returns True when the database is healthy, or raises."""


def select_one(engine: Engine) -> bool:
    """Runs `SELECT 1` on `engine`. True when it returns 1; raises on failure."""
    with engine.connect() as connection:
        return bool(connection.execute(text("SELECT 1")).scalar_one() == 1)


def passes_within_deadline(check: DatabaseCheck, deadline: float = HEALTH_DEADLINE_SECONDS) -> bool:
    """True when `check` returns True within `deadline` seconds.

    False when it returns anything else, raises, or does not finish in time.
    """
    outcome: list[bool] = []
    failure: list[str] = []

    def run() -> None:
        try:
            outcome.append(check() is True)
        except BaseException as exc:  # any failure means "unavailable"
            failure.append(type(exc).__name__)

    worker = threading.Thread(target=run, name="database-health-check", daemon=True)
    worker.start()
    worker.join(deadline)
    if worker.is_alive():
        logger.warning("Database health check failed: %s", TimeoutError.__name__)
        return False
    if failure:
        logger.warning("Database health check failed: %s", failure[0])
        return False
    return bool(outcome and outcome[0])


def database_is_reachable(engine: Engine, deadline: float = HEALTH_DEADLINE_SECONDS) -> bool:
    """True when `SELECT 1` succeeds on `engine` within `deadline` seconds."""
    return passes_within_deadline(lambda: select_one(engine), deadline)
