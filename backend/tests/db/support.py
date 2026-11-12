"""Helpers for the database tests: throwaway databases and Alembic configs.

`TEST_DATABASE_URL` only names a server. Each helper here creates its own
database on it, named `ledgerlens_test_<random hex>`, and drops it afterwards,
so nothing is ever written to the database the URL names, and two test runs
at the same time do not collide.
"""

import os
import secrets
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from alembic.config import Config
from sqlalchemy import text

from ledgerlens.db.session import database_url, make_engine

BACKEND_DIR = Path(__file__).resolve().parents[2]
TEST_DATABASE_URL = "TEST_DATABASE_URL"
SKIP_REASON = "TEST_DATABASE_URL not set"
DATABASE_PREFIX = "ledgerlens_test_"


def server_url_from_environment() -> str | None:
    """`TEST_DATABASE_URL`, or None when it is unset or blank."""
    value = os.environ.get(TEST_DATABASE_URL, "")
    return value if value.strip() else None


def new_database_name() -> str:
    return f"{DATABASE_PREFIX}{secrets.token_hex(8)}"


@contextmanager
def temporary_database(server_url: str) -> Iterator[str]:
    """Creates an empty database on the server, yields its URL, then drops it."""
    name = new_database_name()
    admin = make_engine(server_url).execution_options(isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{name}"'))
        try:
            yield database_url(server_url).set(database=name).render_as_string(hide_password=False)
        finally:
            with admin.connect() as connection:
                connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    finally:
        admin.dispose()


def alembic_config(url: str) -> Config:
    """An Alembic config for the backend migrations, pointed at `url`."""
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    # The config file is parsed with interpolation, so `%` must be doubled.
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return config
