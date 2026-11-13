"""No transaction field, cursor or API key reaches DemoBank's telemetry (#122).

A transactions request with `?cursor=...&limit=...` and the API key header,
answered from a fake page whose fields hold sentinel values. No span
attribute, exported log record or stdout line may contain the cursor, the
key or a transaction field value. No database: the queries are replaced.
"""

import json
from collections.abc import Iterator
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from demobank.api import v1
from demobank.api.cursor import Position, encode_cursor
from demobank.app import create_app
from demobank.config import Settings, get_settings
from demobank.db.transactions import Page, StoredTransaction
from tests.telemetry_support import InMemoryTelemetry, json_lines, log_text, span_text

API_KEY = "sentinel-api-key"
CURSOR = encode_cursor(Position(date(2026, 11, 1), "SENTINEL-CURSOR-TX"))
TRANSACTION = StoredTransaction(
    transaction_id="SENTINEL-TX-ID",
    account_id="acc_operating_001",
    booking_date=date(2026, 11, 2),
    value_date=date(2026, 11, 2),
    amount=Decimal("98765.43"),
    currency="EUR",
    direction="debit",
    counterparty_name="SENTINEL-COUNTERPARTY",
    counterparty_reference="SENTINEL-REFERENCE",
    description="SENTINEL-DESCRIPTION",
    status="booked",
)
SENTINELS = (
    API_KEY,
    CURSOR,
    "SENTINEL",
    "98765.43",
)


def no_database(settings: Settings) -> None:
    """Replaces the database step of the startup."""


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("DEMOBANK_API_KEY", API_KEY)
    monkeypatch.setenv("DEMOBANK_DATABASE_URL", "postgresql://u:pw@127.0.0.1:1/x")
    monkeypatch.setattr(v1, "account_exists", lambda engine, account_id: True)

    def page(engine: Engine, account_id: str, after: Position | None, limit: int) -> Page:
        assert after is not None
        return Page([TRANSACTION], has_more=False)

    monkeypatch.setattr(v1, "transactions_page", page)
    get_settings.cache_clear()
    with TestClient(create_app(database_step=no_database)) as started:
        yield started
    get_settings.cache_clear()


def assert_private(text: str, where: str) -> None:
    for sentinel in SENTINELS:
        assert sentinel not in text, f"{sentinel} in {where}: {text}"
    assert "?" not in text, f"a query string in {where}: {text}"
    assert "x-api-key" not in text.lower(), where
    assert "http.request.header." not in text, where


def test_no_cursor_key_or_transaction_field_reaches_telemetry(
    otel: InMemoryTelemetry, client: TestClient, capsys: pytest.CaptureFixture[str]
) -> None:
    capsys.readouterr()

    response = client.get(
        f"/v1/accounts/acc_operating_001/transactions?cursor={CURSOR}&limit=7",
        headers={"X-API-Key": API_KEY},
    )

    assert response.status_code == 200
    assert response.json()["transactions"][0]["description"] == "SENTINEL-DESCRIPTION"
    spans = otel.finished_spans()
    assert [span.name for span in spans] == ["GET /v1/accounts/{account_id}/transactions"]
    for span in spans:
        assert_private(span_text(span), f"span {span.name}")
    for name, attributes in otel.metric_attributes():
        assert_private(json.dumps(attributes, default=str), f"metric {name}")
    for record in otel.log_records():
        assert_private(log_text(record), "an exported log record")
    for line in json_lines(capsys.readouterr().out):
        assert_private(json.dumps(line), "a stdout line")
