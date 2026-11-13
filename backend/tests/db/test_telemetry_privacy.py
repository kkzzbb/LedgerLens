"""No customer data reaches the database spans either (#122), on PostgreSQL.

The same check as `tests/unit/test_telemetry_privacy.py`, with the real
repositories: one sync against the sentinel fake DemoBank and one
`GET /api/transactions?q=SENTINEL-SEARCH`, both through psycopg-instrumented
connections. The DB spans hold SQL with placeholders only, and the full
database URL appears in no attribute.
"""

import json
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, delete
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session, sessionmaker

from ledgerlens import telemetry
from ledgerlens.api import sync as sync_api
from ledgerlens.api import transactions as transactions_api
from ledgerlens.api.app import create_app
from ledgerlens.config import get_settings
from ledgerlens.connectors.demobank import DemoBankConnector
from ledgerlens.db.models import AnomalyFlag, BankAccount, BankTransaction
from ledgerlens.db.session import make_engine
from tests.telemetry_support import (
    DEMOBANK_URL,
    SENTINEL_API_KEY,
    SENTINELS,
    InMemoryTelemetry,
    MockedHTTPTransport,
    fake_demobank,
    log_text,
    span_text,
)

pytestmark = pytest.mark.db

SENTINEL_SEARCH = "SENTINEL-SEARCH"


@pytest.fixture
def traced_engine(migrated_database_url: URL) -> Iterator[Engine]:
    """An engine whose connections are opened after the psycopg instrumentation."""
    telemetry.instrument_database()
    engine = make_engine(migrated_database_url)
    yield engine
    with Session(engine) as session, session.begin():
        session.execute(delete(AnomalyFlag))
        session.execute(delete(BankTransaction))
        session.execute(delete(BankAccount))
    engine.dispose()


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch, migrated_database_url: URL) -> Iterator[None]:
    monkeypatch.setenv("DATABASE_URL", migrated_database_url.render_as_string(False))
    monkeypatch.setenv("DEMOBANK_API_KEY", SENTINEL_API_KEY)
    monkeypatch.setenv("SYNC_PAGE_SIZE", "1")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.usefixtures("settings")
def test_no_sentinel_and_no_database_url_reaches_telemetry(
    otel: InMemoryTelemetry, traced_engine: Engine, migrated_database_url: URL
) -> None:
    factory = sessionmaker(bind=traced_engine, expire_on_commit=False)

    def connector() -> Iterator[DemoBankConnector]:
        transport = MockedHTTPTransport(fake_demobank)
        with DemoBankConnector(DEMOBANK_URL, SENTINEL_API_KEY, transport=transport) as built:
            yield built

    app = create_app()
    app.dependency_overrides[sync_api.get_connector] = connector
    app.dependency_overrides[sync_api.get_session_factory] = lambda: factory
    app.dependency_overrides[transactions_api.get_session_factory] = lambda: factory
    with TestClient(app) as client:
        synced = client.post("/api/sync")
        searched = client.get(f"/api/transactions?q={SENTINEL_SEARCH}")

    assert synced.status_code == 200
    assert synced.json()["accounts"][0]["created_count"] == 2
    assert searched.status_code == 200

    spans = otel.finished_spans()
    database_spans = [
        span
        for span in spans
        if "db.system" in (span.attributes or {}) or "db.system.name" in (span.attributes or {})
    ]
    assert len(database_spans) > 5, [span.name for span in spans]
    sync_trace = {span.context.trace_id for span in spans if span.name == "POST /api/sync"}
    assert {span.context.trace_id for span in database_spans} >= sync_trace

    full_url = migrated_database_url.render_as_string(hide_password=False)
    plain_url = full_url.replace("postgresql+psycopg://", "postgresql://")
    for span in spans:
        text = span_text(span)
        for sentinel in (*SENTINELS, SENTINEL_SEARCH):
            assert sentinel not in text, f"{sentinel} in span {span.name}: {text}"
        assert full_url not in text
        assert plain_url not in text
        assert "?" not in text, text
    for _, attributes, _ in otel.metric_points():
        text = json.dumps(attributes, default=str)
        assert not any(sentinel in text for sentinel in SENTINELS)
    for record in otel.log_records():
        text = log_text(record)
        assert not any(sentinel in text for sentinel in (*SENTINELS, SENTINEL_SEARCH)), text
        assert full_url not in text
