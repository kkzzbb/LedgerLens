"""Unit tests for `ledgerlens.services.health`: no database needed.

The real `SELECT 1` check is run against addresses where no PostgreSQL
answers, to prove the connect timeout and the deadline without a database.
"""

import logging
import socket
import threading
import time
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine

from ledgerlens.db.session import make_engine
from ledgerlens.services.health import (
    HEALTH_DEADLINE_SECONDS,
    database_is_reachable,
    passes_within_deadline,
)

MARKER_PASSWORD = "MARKERhealthpw42"
HEALTH_LOGGER = "ledgerlens.services.health"


def refused_url() -> str:
    """Nothing listens on port 1: the connection is refused at once."""
    return f"postgresql://ledgerlens:{MARKER_PASSWORD}@127.0.0.1:1/ledgerlens"


@pytest.fixture
def refused_engine() -> Iterator[Engine]:
    engine = make_engine(refused_url())
    yield engine
    engine.dispose()


@pytest.fixture
def silent_port() -> Iterator[int]:
    """A local TCP port that accepts connections but never answers."""
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(16)  # the kernel completes the handshake; nothing reads
    yield server.getsockname()[1]
    server.close()


def health_warnings(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [
        record
        for record in caplog.records
        if record.name == HEALTH_LOGGER and record.levelno == logging.WARNING
    ]


def test_the_deadline_is_two_seconds() -> None:
    assert HEALTH_DEADLINE_SECONDS == 2.0


def test_a_check_returning_true_passes() -> None:
    assert passes_within_deadline(lambda: True) is True


def test_a_check_returning_false_fails() -> None:
    assert passes_within_deadline(lambda: False) is False


def test_a_check_raising_fails_and_logs_the_class_name_only(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def check() -> bool:
        raise ConnectionError(f"secret detail {MARKER_PASSWORD}")

    assert passes_within_deadline(check) is False
    warnings = health_warnings(caplog)
    assert len(warnings) == 1
    assert warnings[0].getMessage() == "Database health check failed: ConnectionError"
    assert MARKER_PASSWORD not in caplog.text


def test_a_slow_check_fails_at_the_deadline(caplog: pytest.LogCaptureFixture) -> None:
    release = threading.Event()

    def check() -> bool:
        release.wait(10)
        return True

    started = time.monotonic()
    try:
        assert passes_within_deadline(check, deadline=0.2) is False
    finally:
        release.set()
    assert time.monotonic() - started < 1
    warnings = health_warnings(caplog)
    assert len(warnings) == 1
    assert warnings[0].getMessage() == "Database health check failed: TimeoutError"


def test_refused_connection_is_unavailable_in_under_3_seconds(refused_engine: Engine) -> None:
    started = time.monotonic()
    assert database_is_reachable(refused_engine) is False
    assert time.monotonic() - started < 3


def test_silent_server_is_unavailable_in_under_3_seconds(silent_port: int) -> None:
    engine = make_engine(f"postgresql://ledgerlens:pw@127.0.0.1:{silent_port}/ledgerlens")
    try:
        started = time.monotonic()
        assert database_is_reachable(engine) is False
        assert time.monotonic() - started < 3
    finally:
        engine.dispose()


def test_failed_check_logs_one_warning_without_the_url_or_password(
    refused_engine: Engine, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG, logger="ledgerlens")
    assert database_is_reachable(refused_engine) is False
    warnings = health_warnings(caplog)
    assert len(warnings) == 1
    assert warnings[0].getMessage() == "Database health check failed: OperationalError"
    assert MARKER_PASSWORD not in caplog.text
    assert "127.0.0.1" not in caplog.text
    assert refused_engine.url.render_as_string(hide_password=True) not in caplog.text
