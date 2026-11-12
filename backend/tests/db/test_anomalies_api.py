"""`GET /api/anomalies` and `POST /api/anomalies/{id}/review` (#27) against PostgreSQL."""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from ledgerlens.api import anomalies as anomalies_api
from ledgerlens.api.app import create_app
from ledgerlens.db.models import AnomalyFlag, BankAccount, BankTransaction
from tests.db.test_transactions_api import add, add_account

pytestmark = pytest.mark.db

T0 = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)


@pytest.fixture
def client(db_session: Session) -> TestClient:
    """The API reading through a session on the test's rolled-back connection."""
    app = create_app()

    def factory() -> Session:
        return Session(bind=db_session.connection(), join_transaction_mode="create_savepoint")

    app.dependency_overrides[anomalies_api.get_session_factory] = lambda: factory
    return TestClient(app)


@pytest.fixture
def account(db_session: Session) -> BankAccount:
    return add_account(db_session, "acc-anomalies")


def flag(
    session: Session, transaction: BankTransaction, rule: str = "large_expense", **fields: Any
) -> AnomalyFlag:
    row = AnomalyFlag(
        rule=rule, bank_transaction_id=transaction.id, reason="Worth a look", **fields
    )
    session.add(row)
    session.flush()
    return row


def get(client: TestClient, **params: Any) -> dict[str, Any]:
    response = client.get("/api/anomalies", params=params)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def ids(body: dict[str, Any]) -> list[int]:
    return [item["id"] for item in body["items"]]


def test_no_flags(client: TestClient) -> None:
    assert get(client) == {"items": [], "total": 0, "limit": 50, "offset": 0}


def test_item_shape(client: TestClient, db_session: Session, account: BankAccount) -> None:
    earlier = add(
        db_session,
        account,
        booking_date=date(2026, 10, 30),
        counterparty_name="Acme",
        amount=Decimal("1250"),
        category="inventory",
    )
    later = add(db_session, account, counterparty_name="Acme", amount=Decimal("1250.5"))
    row = flag(db_session, later, "possible_duplicate", related_transaction_id=earlier.id)

    [item] = get(client)["items"]

    assert item["id"] == row.id
    assert (item["rule"], item["status"], item["reason"]) == (
        "possible_duplicate",
        "open",
        "Worth a look",
    )
    assert item["created_at"] is not None
    assert item["reviewed_at"] is None
    assert item["transaction"] == {
        "id": later.id,
        "booking_date": "2026-11-01",
        "counterparty_name": "Acme",
        "amount": "1250.50",
        "category": None,
    }
    assert item["related_transaction"] == {
        "id": earlier.id,
        "booking_date": "2026-10-30",
        "counterparty_name": "Acme",
        "amount": "1250.00",
        "category": "inventory",
    }


def test_a_flag_without_related_transaction(
    client: TestClient, db_session: Session, account: BankAccount
) -> None:
    flag(db_session, add(db_session, account))

    assert get(client)["items"][0]["related_transaction"] is None


def test_newest_first_then_id_descending(
    client: TestClient, db_session: Session, account: BankAccount
) -> None:
    old = flag(db_session, add(db_session, account), created_at=T0)
    tied_a = flag(db_session, add(db_session, account), created_at=T0.replace(hour=10))
    tied_b = flag(db_session, add(db_session, account), created_at=T0.replace(hour=10))

    assert ids(get(client)) == [tied_b.id, tied_a.id, old.id]


def test_filters_alone_and_together(
    client: TestClient, db_session: Session, account: BankAccount
) -> None:
    t1, t2, t3 = (add(db_session, account) for _ in range(3))
    open_large = flag(db_session, t1, created_at=T0)
    reviewed_large = flag(db_session, t2, status="reviewed", reviewed_at=T0, created_at=T0)
    open_duplicate = flag(
        db_session, t3, "possible_duplicate", related_transaction_id=t1.id, created_at=T0
    )

    assert set(ids(get(client, status="open"))) == {open_large.id, open_duplicate.id}
    assert set(ids(get(client, status="reviewed"))) == {reviewed_large.id}
    assert set(ids(get(client, rule="large_expense"))) == {open_large.id, reviewed_large.id}
    assert ids(get(client, status="open", rule="large_expense")) == [open_large.id]


def test_paging_and_total(client: TestClient, db_session: Session, account: BankAccount) -> None:
    rows = [flag(db_session, add(db_session, account), created_at=T0) for _ in range(3)]

    body = get(client, limit=1, offset=1)

    assert body["total"] == 3
    assert (body["limit"], body["offset"]) == (1, 1)
    assert ids(body) == [rows[1].id]


@pytest.mark.parametrize(
    "params",
    [
        {"status": "closed"},
        {"rule": "fraud"},
        {"limit": 0},
        {"limit": 201},
        {"offset": -1},
    ],
)
def test_invalid_parameters_return_422(client: TestClient, params: dict[str, Any]) -> None:
    assert client.get("/api/anomalies", params=params).status_code == 422


def test_review_an_open_flag(client: TestClient, db_session: Session, account: BankAccount) -> None:
    row = flag(db_session, add(db_session, account))

    response = client.post(f"/api/anomalies/{row.id}/review")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == row.id
    assert body["status"] == "reviewed"
    assert body["reviewed_at"] is not None
    assert body["transaction"]["amount"] == "10.00"
    assert get(client, status="reviewed")["total"] == 1


def test_review_an_already_reviewed_flag_changes_nothing(
    client: TestClient, db_session: Session, account: BankAccount
) -> None:
    row = flag(db_session, add(db_session, account), status="reviewed", reviewed_at=T0)

    response = client.post(f"/api/anomalies/{row.id}/review")

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "reviewed"
    assert datetime.fromisoformat(response.json()["reviewed_at"]) == T0
    db_session.refresh(row)
    assert row.reviewed_at == T0


def test_review_an_unknown_id(client: TestClient) -> None:
    response = client.post("/api/anomalies/999999999/review")

    assert response.status_code == 404
    assert response.json() == {"detail": "anomaly flag not found"}


def test_review_a_non_integer_id(client: TestClient) -> None:
    assert client.post("/api/anomalies/abc/review").status_code == 422


def test_the_list_does_not_say_fraud(
    client: TestClient, db_session: Session, account: BankAccount
) -> None:
    flag(db_session, add(db_session, account))

    response = client.get("/api/anomalies")

    assert "fraud" not in response.text.casefold()
