"""SQLAlchemy engine and sessions.

Importing this module reads no settings and opens no connection: the engine
is built on the first call to `get_engine()`.

The database URL may use the `postgresql://` or `postgres://` scheme (as in
`.env.example`); the psycopg 3 driver is added here. Error messages never
contain the URL, which holds the database password.
"""

from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.orm import Session, sessionmaker

from ledgerlens.config import get_settings

DRIVER_SCHEME = "postgresql+psycopg"
# Seconds libpq waits for a connection to be established (its minimum is 2).
DEFAULT_CONNECT_TIMEOUT = 5
_PLAIN_SCHEMES = {"postgresql", "postgres"}


_UNSUPPORTED_SCHEME = (
    "database URL has an unsupported scheme; expected postgresql://, "
    "postgres:// or postgresql+psycopg://"
)


def _driver_scheme(scheme: str) -> str:
    if scheme in _PLAIN_SCHEMES or scheme == DRIVER_SCHEME:
        return DRIVER_SCHEME
    raise ValueError(_UNSUPPORTED_SCHEME)


def database_url(url: str | URL) -> URL:
    """The URL with the psycopg 3 driver, or `ValueError` for another scheme.

    Accepts a string or a SQLAlchemy `URL` (whose repr hides the password).
    The error message does not contain the URL.
    """
    if isinstance(url, URL):
        return url.set(drivername=_driver_scheme(url.drivername))
    scheme, separator, rest = url.strip().partition("://")
    if not separator:
        raise ValueError("database URL has no scheme; expected postgresql://")
    scheme = _driver_scheme(scheme)
    try:
        return make_url(f"{scheme}://{rest}")
    except (ArgumentError, ValueError):
        # SQLAlchemy's message may quote the URL, so it is not chained.
        pass
    raise ValueError("database URL could not be parsed")


def make_engine(url: str | URL, *, connect_timeout: int = DEFAULT_CONNECT_TIMEOUT) -> Engine:
    """A synchronous engine for `url`, checking connections before use.

    `connect_timeout` (seconds) is handed to the driver, so connecting to a
    server that does not answer fails instead of hanging.

    `search_path` is pinned to `public`. PostgreSQL's default `"$user", public`
    would otherwise make `ledgerlens` the default schema whenever the database
    user is named `ledgerlens`, and Alembic would then no longer see the
    `ledgerlens` tables when comparing models and migrations. Every LedgerLens
    table is schema-qualified, so nothing else depends on it.
    """
    return create_engine(
        database_url(url),
        pool_pre_ping=True,
        echo=False,
        connect_args={"connect_timeout": connect_timeout, "options": "-c search_path=public"},
    )


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """The application engine, built once from `DATABASE_URL`."""
    return make_engine(get_settings().database_url.get_secret_value())


def get_sessionmaker() -> sessionmaker[Session]:
    """A session factory bound to `get_engine()`."""
    return _sessionmaker()


@lru_cache(maxsize=1)
def _sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)
