"""Helpers for DemoBank's database tests: throwaway databases.

Written again from `backend/tests/db/support.py` (#6): DemoBank imports
nothing from `ledgerlens`.

`TEST_DATABASE_URL` only names a server. Each helper here creates its own
database on it, named `demobank_test_<random hex>`, and drops it afterwards,
so nothing is ever written to the database the URL names, and two test runs
at the same time do not collide.

The password must never reach test output. Pytest prints the arguments of
every function in a failure traceback, so URLs are passed around as
SQLAlchemy `URL` objects, whose repr hides the password, never as strings.
Connection failures are turned into a one-line failure without the driver
traceback, whose frames hold the password.
"""

import os
import secrets
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import DBAPIError

from demobank.db.startup import make_engine
from demobank.db.url import database_url

DEMOBANK_DIR = Path(__file__).resolve().parents[2]
TEST_DATABASE_URL = "TEST_DATABASE_URL"
SKIP_REASON = "TEST_DATABASE_URL not set"
DATABASE_PREFIX = "demobank_test_"
MASK = "***"


def _raw_server_url() -> str | None:
    value = os.environ.get(TEST_DATABASE_URL, "")
    return value if value.strip() else None


def database_configured() -> bool:
    """True when `TEST_DATABASE_URL` is set to a non-blank value."""
    return _raw_server_url() is not None


def server_password() -> str | None:
    """The password in `TEST_DATABASE_URL`, to mask it in test output."""
    raw = _raw_server_url()
    if raw is None:
        return None
    try:
        password = database_url(raw).password
    except ValueError:
        return None
    return str(password) if password else None


def mask_password(message: str) -> str:
    """`message` with the `TEST_DATABASE_URL` password replaced by `***`."""
    password = server_password()
    if password:
        message = message.replace(password, MASK)
    return message


def server_url_from_environment() -> URL:
    """`TEST_DATABASE_URL` as a `URL`. Fails the test (without the URL) when invalid."""
    raw = _raw_server_url()
    if raw is None:
        pytest.skip(SKIP_REASON)
    try:
        return database_url(raw)
    except ValueError as exc:
        message = f"{TEST_DATABASE_URL}: {exc}"
    pytest.fail(message, pytrace=False)


def execute(engine: Engine, statement: str) -> None:
    """Runs `statement` in autocommit mode. A database error fails the test
    with one line, without the driver traceback."""
    try:
        with engine.connect() as connection:
            connection.execute(text(statement))
        return
    except DBAPIError as exc:
        reason = str(exc.orig).strip().splitlines()[0] if exc.orig else type(exc).__name__
    # Outside the `except` block so the driver error is not chained.
    pytest.fail(f"{TEST_DATABASE_URL} server: {mask_password(reason)}", pytrace=False)


def check_server(server_url: URL) -> None:
    """Fails with one line when the server cannot be reached or rejects the login."""
    engine = make_engine(server_url).execution_options(isolation_level="AUTOCOMMIT")
    try:
        execute(engine, "SELECT 1")
    finally:
        engine.dispose()


def new_database_name() -> str:
    return f"{DATABASE_PREFIX}{secrets.token_hex(8)}"


@contextmanager
def temporary_database(server_url: URL) -> Iterator[URL]:
    """Creates an empty database on the server, yields its URL, then drops it."""
    name = new_database_name()
    admin = make_engine(server_url).execution_options(isolation_level="AUTOCOMMIT")
    try:
        execute(admin, f'CREATE DATABASE "{name}"')
        try:
            yield server_url.set(database=name)
        finally:
            execute(admin, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    finally:
        admin.dispose()
