"""Fixtures for DemoBank's tests that need PostgreSQL (the `db` marker).

Written again from `backend/tests/db/conftest.py` (#6):

- `empty_database_url`: a fresh empty database per test
- `engine`: an engine on that database, disposed after the test

The URLs are SQLAlchemy `URL` objects, whose repr hides the password. Every
`db` test is skipped when `TEST_DATABASE_URL` is unset or blank.

As a last line of defence, the reports of the tests in this folder have the
`TEST_DATABASE_URL` password replaced by `***` (for example a driver error
raised in the middle of a test, whose traceback frames hold the password).
"""

from collections.abc import Generator, Iterator

import pytest
from _pytest.reports import TestReport
from pluggy import Result
from sqlalchemy import Engine
from sqlalchemy.engine import URL

from demobank.db.startup import make_engine
from tests.db.support import (
    SKIP_REASON,
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


@pytest.fixture
def engine(empty_database_url: URL) -> Iterator[Engine]:
    """An engine on the test's empty database."""
    created = make_engine(empty_database_url)
    yield created
    created.dispose()
