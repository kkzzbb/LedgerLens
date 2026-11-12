"""`GET /api/accounts` (#24) against PostgreSQL."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from ledgerlens.api import accounts as accounts_api
from ledgerlens.api.app import create_app
from ledgerlens.db.models import BankAccount

pytestmark = pytest.mark.db

KEYS = {
    "id",
    "provider",
    "external_account_id",
    "display_name",
    "currency",
    "last_balance",
    "last_balance_at",
    "last_sync_at",
    "last_sync_status",
    "last_sync_error",
    "last_successful_sync_at",
}
LAST_KEYS = {key for key in KEYS if key.startswith("last_")}

BALANCE_AT = datetime(2026, 11, 12, 8, 0, 0, tzinfo=UTC)
SYNC_AT = datetime(2026, 11, 12, 8, 0, 5, tzinfo=UTC)


@pytest.fixture
def client(db_session: Session) -> TestClient:
    """The API reading through a session on the test's rolled-back connection."""
    app = create_app()

    def factory() -> Session:
        return Session(bind=db_session.connection(), join_transaction_mode="create_savepoint")

    app.dependency_overrides[accounts_api.get_session_factory] = lambda: factory
    return TestClient(app)


def add_account(session: Session, external_id: str, **fields: Any) -> BankAccount:
    account = BankAccount(
        provider="demobank",
        external_account_id=external_id,
        display_name="Business account",
        currency="EUR",
        last_cursor="cursor-secret",
        **fields,
    )
    session.add(account)
    session.flush()
    return account


def synced(balance: str) -> dict[str, Any]:
    return {
        "last_balance": Decimal(balance),
        "last_balance_at": BALANCE_AT,
        "last_sync_at": SYNC_AT,
        "last_sync_status": "succeeded",
        "last_successful_sync_at": SYNC_AT,
    }


def get(client: TestClient) -> list[dict[str, Any]]:
    response = client.get("/api/accounts")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    assert set(body) == {"accounts"}
    accounts: list[dict[str, Any]] = body["accounts"]
    return accounts


def parse(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    assert parsed.tzinfo is not None
    return parsed


def test_no_accounts(client: TestClient) -> None:
    assert get(client) == []


def test_synced_accounts_ordered_by_id(client: TestClient, db_session: Session) -> None:
    first = add_account(db_session, "acc-1", **synced("12450.3"))
    second = add_account(db_session, "acc-2", **synced("-5000"))
    third = add_account(db_session, "acc-3", **synced("0"))

    accounts = get(client)

    assert [item["id"] for item in accounts] == [first.id, second.id, third.id]
    assert [item["last_balance"] for item in accounts] == ["12450.30", "-5000.00", "0.00"]
    item = accounts[0]
    assert set(item) == KEYS
    assert item | {
        "last_balance_at": None,
        "last_sync_at": None,
        "last_successful_sync_at": None,
    } == {
        "id": first.id,
        "provider": "demobank",
        "external_account_id": "acc-1",
        "display_name": "Business account",
        "currency": "EUR",
        "last_balance": "12450.30",
        "last_balance_at": None,
        "last_sync_at": None,
        "last_sync_status": "succeeded",
        "last_sync_error": None,
        "last_successful_sync_at": None,
    }
    assert parse(item["last_balance_at"]) == BALANCE_AT
    assert parse(item["last_sync_at"]) == SYNC_AT
    assert parse(item["last_successful_sync_at"]) == SYNC_AT


def test_never_synced_account(client: TestClient, db_session: Session) -> None:
    add_account(db_session, "acc-1")

    (item,) = get(client)

    assert set(item) == KEYS
    assert {key: item[key] for key in LAST_KEYS} == dict.fromkeys(LAST_KEYS)


def test_failed_after_success_keeps_last_balance(client: TestClient, db_session: Session) -> None:
    failed_at = datetime(2026, 11, 12, 9, 0, 0, tzinfo=UTC)
    add_account(
        db_session,
        "acc-1",
        **synced("12450.30")
        | {
            "last_sync_at": failed_at,
            "last_sync_status": "failed",
            "last_sync_error": "provider unavailable",
        },
    )

    (item,) = get(client)

    assert item["last_balance"] == "12450.30"
    assert parse(item["last_balance_at"]) == BALANCE_AT
    assert parse(item["last_successful_sync_at"]) == SYNC_AT
    assert parse(item["last_sync_at"]) == failed_at
    assert item["last_sync_status"] == "failed"
    assert item["last_sync_error"] == "provider unavailable"
