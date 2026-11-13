"""Shared fixtures for every backend test."""

import logging
from collections.abc import Iterator

import pytest

from ledgerlens.telemetry import JsonFormatter
from tests.telemetry_support import InMemoryTelemetry, in_memory_telemetry


@pytest.fixture(autouse=True)
def no_otlp_export(monkeypatch: pytest.MonkeyPatch) -> None:
    """The developer's shell never turns OTLP export on in a test (#122)."""
    monkeypatch.delenv("OTEL_ENABLED", raising=False)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)


@pytest.fixture(autouse=True)
def no_json_stdout_handler_left_behind() -> Iterator[None]:
    """`create_app()` adds a JSON stdout handler to the root logger; each test starts without.

    Otherwise a test that prints to stdout (the CLI) would also read the log
    lines of every test that created an app before it.
    """
    yield
    root = logging.getLogger()
    for handler in list(root.handlers):
        if isinstance(handler.formatter, JsonFormatter):
            root.removeHandler(handler)


@pytest.fixture
def otel() -> Iterator[InMemoryTelemetry]:
    """The in-memory exporters, emptied before and after the test."""
    installed = in_memory_telemetry()
    installed.clear()
    yield installed
    installed.clear()
