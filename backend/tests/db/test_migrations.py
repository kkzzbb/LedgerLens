"""The Alembic migrations on real PostgreSQL databases."""

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, text
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session

from ledgerlens.db import models  # noqa: F401  (registers the models on Base.metadata)
from ledgerlens.db.autogenerate import context_options
from ledgerlens.db.base import Base
from ledgerlens.db.session import make_engine
from tests.db.support import alembic_config

pytestmark = pytest.mark.db


def script_head(url: URL) -> str:
    head = ScriptDirectory.from_config(alembic_config(url)).get_current_head()
    assert head is not None
    return head


def version_rows(url: URL) -> list[str]:
    engine = make_engine(url)
    try:
        with engine.connect() as connection:
            rows = connection.execute(text("SELECT version_num FROM ledgerlens.alembic_version"))
            return [row[0] for row in rows]
    finally:
        engine.dispose()


def current_revision(url: URL) -> str | None:
    engine = make_engine(url)
    try:
        with engine.connect() as connection:
            context = MigrationContext.configure(connection, opts=context_options())
            return context.get_current_revision()
    finally:
        engine.dispose()


def test_upgrade_head_on_an_empty_database(empty_database_url: URL) -> None:
    command.upgrade(alembic_config(empty_database_url), "head")

    assert current_revision(empty_database_url) == script_head(empty_database_url)
    assert version_rows(empty_database_url) == [script_head(empty_database_url)]


def test_upgrade_head_twice(empty_database_url: URL) -> None:
    config = alembic_config(empty_database_url)
    command.upgrade(config, "head")
    command.upgrade(config, "head")

    assert version_rows(empty_database_url) == [script_head(empty_database_url)]


def test_upgrade_downgrade_upgrade(empty_database_url: URL) -> None:
    config = alembic_config(empty_database_url)
    command.upgrade(config, "head")
    command.downgrade(config, "base")

    assert version_rows(empty_database_url) == []

    command.upgrade(config, "head")
    assert version_rows(empty_database_url) == [script_head(empty_database_url)]


def test_models_and_migrations_do_not_drift(migrated_engine: Engine) -> None:
    with migrated_engine.connect() as connection:
        context = MigrationContext.configure(connection, opts=context_options())
        assert compare_metadata(context, Base.metadata) == []


def test_autogenerate_ignores_other_schemas(empty_database_url: URL) -> None:
    command.upgrade(alembic_config(empty_database_url), "head")
    engine = make_engine(empty_database_url)
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE SCHEMA demobank_sim"))
            connection.execute(text("CREATE TABLE demobank_sim.accounts (id integer)"))
            connection.execute(text("CREATE TABLE public.stray (id integer)"))
        with engine.connect() as connection:
            context = MigrationContext.configure(connection, opts=context_options())
            assert compare_metadata(context, Base.metadata) == []
    finally:
        engine.dispose()


def test_db_session_is_on_the_migrated_database(
    db_session: Session, migrated_database_url: URL
) -> None:
    version = db_session.execute(text("SELECT version_num FROM ledgerlens.alembic_version"))
    assert version.scalar_one() == script_head(migrated_database_url)


def test_db_session_is_rolled_back(db_session: Session, migrated_engine: Engine) -> None:
    db_session.execute(text("CREATE TABLE ledgerlens.rollback_probe (id integer)"))
    db_session.commit()

    with migrated_engine.connect() as other:
        found = other.execute(text("SELECT to_regclass('ledgerlens.rollback_probe')"))
        assert found.scalar_one() is None
