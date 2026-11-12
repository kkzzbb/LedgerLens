"""Fixtures for the tests that need PostgreSQL (the `db` marker).

Later issues reuse them:

- `empty_database_url`: a fresh empty database per test
- `migrated_database_url`: one database per run, migrated to head
- `db_session`: a session on the migrated database, rolled back after each test

Every `db` test is skipped when `TEST_DATABASE_URL` is unset or blank.
"""

from collections.abc import Iterator

import pytest
from alembic import command
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from ledgerlens.db.session import make_engine
from tests.db.support import (
    SKIP_REASON,
    alembic_config,
    server_url_from_environment,
    temporary_database,
)


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if server_url_from_environment() is not None:
        return
    skip = pytest.mark.skip(reason=SKIP_REASON)
    for item in items:
        if item.get_closest_marker("db") is not None:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def server_url() -> str:
    """`TEST_DATABASE_URL`: the server the test databases are created on."""
    url = server_url_from_environment()
    if url is None:
        pytest.skip(SKIP_REASON)
    return url


@pytest.fixture
def empty_database_url(server_url: str) -> Iterator[str]:
    """The URL of a new empty database, dropped after the test."""
    with temporary_database(server_url) as url:
        yield url


@pytest.fixture(scope="session")
def migrated_database_url(server_url: str) -> Iterator[str]:
    """The URL of a database migrated to head, shared by the run, dropped after it."""
    with temporary_database(server_url) as url:
        command.upgrade(alembic_config(url), "head")
        yield url


@pytest.fixture(scope="session")
def migrated_engine(migrated_database_url: str) -> Iterator[Engine]:
    engine = make_engine(migrated_database_url)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(migrated_engine: Engine) -> Iterator[Session]:
    """A session on the migrated database. Everything it does is rolled back.

    `session.commit()` inside a test only releases a savepoint; the outer
    transaction is rolled back after the test.
    """
    with migrated_engine.connect() as connection:
        transaction = connection.begin()
        session = Session(
            bind=connection,
            join_transaction_mode="create_savepoint",
            expire_on_commit=False,
        )
        try:
            yield session
        finally:
            session.close()
            transaction.rollback()
