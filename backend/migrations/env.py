"""Alembic environment for the LedgerLens backend.

The database URL comes from the Alembic config when the caller set
`sqlalchemy.url` (the tests do), otherwise from the `DATABASE_URL` environment
variable. A blank value counts as unset. Only `DATABASE_URL` is read, so
migrating needs no other setting.

The version table lives in the `ledgerlens` schema, which is created here
before Alembic touches it, so the first run on an empty database works.
Messages never contain the URL or the password.
"""

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.exc import DBAPIError

from ledgerlens.db.autogenerate import context_options
from ledgerlens.db.base import SCHEMA, Base
from ledgerlens.db.session import database_url, make_engine

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)
target_metadata = Base.metadata


def _url() -> URL:
    """The database URL, parsed. No function here takes the raw string as an
    argument, so a traceback cannot show it."""
    raw = config.get_main_option("sqlalchemy.url") or os.environ.get("DATABASE_URL") or ""
    if not raw.strip():
        raise SystemExit("DATABASE_URL is required but not set")
    try:
        return database_url(raw)
    except ValueError as exc:
        message = str(exc)
    raise SystemExit(message)


def _without_password(message: str, url: URL) -> str:
    if url.password:
        message = message.replace(str(url.password), "***")
    return message


def run_migrations_offline() -> None:
    """Writes the SQL to stdout instead of running it (`alembic upgrade --sql`)."""
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        **context_options(),
    )
    with context.begin_transaction():
        context.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
        context.run_migrations()


def run_migrations_online() -> None:
    """Runs the migrations on the database."""
    url = _url()
    engine = make_engine(url)
    try:
        try:
            connection = engine.connect()
        except DBAPIError as exc:
            reason = str(exc.orig).strip().splitlines()[0] if exc.orig else type(exc).__name__
            message = f"Cannot connect to the database: {_without_password(reason, url)}"
        else:
            with connection:
                connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}"))
                connection.commit()
                context.configure(
                    connection=connection,
                    target_metadata=target_metadata,
                    **context_options(),
                )
                with context.begin_transaction():
                    context.run_migrations()
            return
    finally:
        engine.dispose()
    # Raised outside the `except` block so the driver error, whose traceback
    # could show connection details, is not chained.
    raise SystemExit(message)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
