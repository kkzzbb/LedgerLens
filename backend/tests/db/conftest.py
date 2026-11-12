"""Fixtures for the tests that need PostgreSQL (the `db` marker).

Later issues reuse them:

- `empty_database_url`: a fresh empty database per test
- `migrated_database_url`: one database per run, migrated to head
- `db_session`: a session on the migrated database, rolled back after each test

The URLs are SQLAlchemy `URL` objects, whose repr hides the password. Every
`db` test is skipped when `TEST_DATABASE_URL` is unset or blank.

As a last line of defence, the reports of the tests in this folder have the
`TEST_DATABASE_URL` password replaced by `***` (for example a driver error
raised in the middle of a test, whose traceback frames hold the password).
"""

from collections.abc import Generator, Iterator

import pytest
from _pytest.reports import TestReport
from alembic import command
from pluggy import Result
from sqlalchemy import Engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session

from ledgerlens.db.session import make_engine
from tests.db.support import (
    SKIP_REASON,
    alembic_config,
    check_server,
    database_configured,
    mask_password,
    server_password,
    server_url_from_environment,
    temporary_database,
)


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if database_configured():
        return
    skip = pytest.mark.skip(reason=SKIP_REASON)
    for item in items:
        if item.get_closest_marker("db") is not None:
            item.add_marker(skip)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item, call: pytest.CallInfo[None]
) -> Generator[None, Result[TestReport], None]:
    outcome = yield
    password = server_password()
    if not password:
        return
    report = outcome.get_result()
    if report.longrepr is not None:
        text = str(report.longrepr)
        if password in text:
            report.longrepr = mask_password(text)
    report.sections = [(title, mask_password(content)) for title, content in report.sections]


@pytest.fixture(scope="session")
def server_url() -> URL:
    """`TEST_DATABASE_URL`: the server the test databases are created on."""
    url = server_url_from_environment()
    check_server(url)
    return url


@pytest.fixture
def empty_database_url(server_url: URL) -> Iterator[URL]:
    """The URL of a new empty database, dropped after the test."""
    with temporary_database(server_url) as url:
        yield url


@pytest.fixture(scope="session")
def migrated_database_url(server_url: URL) -> Iterator[URL]:
    """The URL of a database migrated to head, shared by the run, dropped after it."""
    with temporary_database(server_url) as url:
        command.upgrade(alembic_config(url), "head")
        yield url


@pytest.fixture(scope="session")
def migrated_engine(migrated_database_url: URL) -> Iterator[Engine]:
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
