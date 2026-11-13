"""No customer data and no credential reaches telemetry (#122).

One sync through `TestClient`, against a fake DemoBank whose records hold
sentinel values (description, counterparty, reference, an IBAN-like account
number, amount 98765.43, API key `sentinel-api-key`, a cursor), and one
`GET /api/transactions?q=SENTINEL-SEARCH`. Then every span (name, attributes,
events, status), every metric data point attribute, every exported log record
and every stdout line must be free of the sentinels, of query strings and of
captured HTTP headers. The session factory and repositories are the in-memory
fakes of `test_sync_service.py`, so no database is needed.
"""

import json
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from ledgerlens.api import sync as sync_api
from ledgerlens.api import transactions as transactions_api
from ledgerlens.api.app import create_app
from ledgerlens.config import get_settings
from ledgerlens.connectors.demobank import DemoBankConnector
from ledgerlens.db.repositories.transactions import TransactionPage
from tests.telemetry_support import (
    DEMOBANK_URL,
    SENTINEL_API_KEY,
    SENTINELS,
    InMemoryTelemetry,
    MockedHTTPTransport,
    fake_demobank,
    json_lines,
    log_text,
    span_text,
)
from tests.unit.test_sync_service import Store, factory, fake_repositories


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> Store:
    """The in-memory repositories of `test_sync_service.py`."""
    return fake_repositories(monkeypatch)


SENTINEL_SEARCH = "SENTINEL-SEARCH"
DATABASE_PASSWORD = "SENTINEL-DB-PASSWORD"


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("DATABASE_URL", f"postgresql://u:{DATABASE_PASSWORD}@localhost/x")
    monkeypatch.setenv("DEMOBANK_API_KEY", SENTINEL_API_KEY)
    monkeypatch.setenv("SYNC_PAGE_SIZE", "1")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def assert_private(text: str, where: str) -> None:
    for sentinel in (*SENTINELS, SENTINEL_SEARCH, DATABASE_PASSWORD):
        assert sentinel not in text, f"{sentinel} in {where}: {text}"
    assert "?" not in text, f"a query string in {where}: {text}"
    assert "http.request.header." not in text, where
    assert "http.response.header." not in text, where
    assert "x-api-key" not in text.lower(), where


@pytest.mark.usefixtures("settings")
def test_no_sentinel_reaches_spans_metrics_or_logs(
    otel: InMemoryTelemetry,
    store: Store,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def connector() -> Iterator[DemoBankConnector]:
        transport = MockedHTTPTransport(fake_demobank)
        with DemoBankConnector(DEMOBANK_URL, SENTINEL_API_KEY, transport=transport) as built:
            yield built

    monkeypatch.setattr(transactions_api, "list_transactions", lambda *args: TransactionPage([], 0))
    app = create_app()
    app.dependency_overrides[sync_api.get_connector] = connector
    app.dependency_overrides[sync_api.get_session_factory] = lambda: factory(store)
    app.dependency_overrides[transactions_api.get_session_factory] = lambda: factory(store)
    capsys.readouterr()

    with TestClient(app) as client:
        synced = client.post("/api/sync")
        searched = client.get(f"/api/transactions?q={SENTINEL_SEARCH}&limit=5")

    assert synced.status_code == 200
    assert synced.json()["accounts"][0]["created_count"] == 2  # the sentinels were synced
    assert searched.status_code == 200

    spans = otel.finished_spans()
    assert {span.name for span in spans} >= {
        "POST /api/sync",
        "GET /api/transactions",
        "GET",
        "sync account",
        "anomaly rule",
    }
    for span in spans:
        assert_private(span_text(span), f"span {span.name}")

    points = otel.metric_points()
    assert points
    for name, attributes, _ in points:
        assert_private(json.dumps(attributes, default=str), f"metric {name}")

    records = otel.log_records()
    assert any(record.log_record.body == "sync finished" for record in records)
    for record in records:
        assert_private(log_text(record), "an exported log record")

    lines = list(json_lines(capsys.readouterr().out))
    assert any(line["message"] == "sync finished" for line in lines)
    for line in lines:
        assert_private(json.dumps(line), "a stdout line")
