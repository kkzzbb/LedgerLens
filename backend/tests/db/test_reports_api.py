"""`GET /api/reports/monthly` and `GET /api/reports/expenses` (#43) against PostgreSQL."""

import itertools
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from ledgerlens.api import reports as reports_api
from ledgerlens.api.app import create_app
from ledgerlens.db.models import BankAccount, BankTransaction

pytestmark = pytest.mark.db

_ids = itertools.count(1)

EXPENSE_KEYS = ["rent", "software", "utilities", "inventory", "supplier_other", "other"]


@pytest.fixture
def client(db_session: Session) -> TestClient:
    """The API reading through a session on the test's rolled-back connection."""
    app = create_app()

    def factory() -> Session:
        return Session(bind=db_session.connection(), join_transaction_mode="create_savepoint")

    app.dependency_overrides[reports_api.get_session_factory] = lambda: factory
    return TestClient(app)


def add_account(session: Session, external_id: str) -> BankAccount:
    account = BankAccount(
        provider="demobank", external_account_id=external_id, display_name="A", currency="EUR"
    )
    session.add(account)
    session.flush()
    return account


def add(
    session: Session,
    account: BankAccount,
    booking_date: date,
    amount: str,
    direction: str = "debit",
    category: str | None = "other",
    status: str = "booked",
) -> None:
    session.add(
        BankTransaction(
            bank_account_id=account.id,
            provider="demobank",
            external_transaction_id=f"r-{next(_ids)}",
            booking_date=booking_date,
            amount=Decimal(amount),
            currency="EUR",
            direction=direction,
            status=status,
            category=category,
            source_metadata={},
        )
    )
    session.flush()


def get(client: TestClient, path: str, first: str, last: str) -> dict[str, Any]:
    response = client.get(f"/api/reports/{path}", params={"from": first, "to": last})
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def expense_amounts(body: dict[str, Any]) -> dict[str, tuple[str, list[str]]]:
    return {c["key"]: (c["total"], [m["amount"] for m in c["months"]]) for c in body["categories"]}


def test_empty_database_returns_zeros(client: TestClient) -> None:
    monthly = get(client, "monthly", "2026-10", "2026-11")
    assert monthly == {
        "from": "2026-10",
        "to": "2026-11",
        "currency": "EUR",
        "months": [
            {"month": m, "money_in": "0.00", "money_out": "0.00", "net": "0.00"}
            for m in ("2026-10", "2026-11")
        ],
    }
    expenses = get(client, "expenses", "2026-10", "2026-11")
    assert expenses["from"] == "2026-10"
    assert expenses["to"] == "2026-11"
    assert expenses["currency"] == "EUR"
    assert [(c["key"], c["name"]) for c in expenses["categories"]] == [
        ("rent", "Rent"),
        ("software", "Software"),
        ("utilities", "Utilities"),
        ("inventory", "Inventory"),
        ("supplier_other", "Other suppliers"),
        ("other", "Other"),
    ]
    assert expense_amounts(expenses) == {k: ("0.00", ["0.00", "0.00"]) for k in EXPENSE_KEYS}


def test_hand_calculated_dataset(client: TestClient, db_session: Session) -> None:
    a = add_account(db_session, "acc-a")
    b = add_account(db_session, "acc-b")
    # September
    add(db_session, a, date(2026, 9, 1), "1500.00", "credit", "revenue")
    add(db_session, a, date(2026, 9, 5), "1000.00", category="rent")
    add(db_session, b, date(2026, 9, 10), "49.99", category="software")
    add(db_session, b, date(2026, 9, 15), "30.00", category=None)
    add(db_session, a, date(2026, 9, 30), "120.51", category="utilities")
    # October: nothing
    # November
    add(db_session, a, date(2026, 11, 1), "1000.00", category="rent")
    add(db_session, b, date(2026, 11, 12), "250.25", category="inventory")
    add(db_session, a, date(2026, 11, 20), "75.50", category="supplier_other")
    add(db_session, a, date(2026, 11, 25), "100.00", category="inventory", status="pending")
    add(db_session, b, date(2026, 11, 30), "19.99", category="other")
    # Outside the range
    add(db_session, a, date(2026, 8, 31), "999.00", category="rent")
    add(db_session, b, date(2026, 12, 1), "777.00", "credit", "revenue")

    monthly = get(client, "monthly", "2026-09", "2026-11")
    assert monthly["months"] == [
        {"month": "2026-09", "money_in": "1500.00", "money_out": "1200.50", "net": "299.50"},
        {"month": "2026-10", "money_in": "0.00", "money_out": "0.00", "net": "0.00"},
        {"month": "2026-11", "money_in": "0.00", "money_out": "1445.74", "net": "-1445.74"},
    ]

    expenses = get(client, "expenses", "2026-09", "2026-11")
    assert [c["key"] for c in expenses["categories"]] == EXPENSE_KEYS
    assert [m["month"] for m in expenses["categories"][0]["months"]] == [
        "2026-09",
        "2026-10",
        "2026-11",
    ]
    assert expense_amounts(expenses) == {
        "rent": ("2000.00", ["1000.00", "0.00", "1000.00"]),
        "software": ("49.99", ["49.99", "0.00", "0.00"]),
        "utilities": ("120.51", ["120.51", "0.00", "0.00"]),
        "inventory": ("350.25", ["0.00", "0.00", "350.25"]),
        "supplier_other": ("75.50", ["0.00", "0.00", "75.50"]),
        "other": ("49.99", ["30.00", "0.00", "19.99"]),
    }


def test_boundaries_with_leap_february(client: TestClient, db_session: Session) -> None:
    account = add_account(db_session, "acc-a")
    add(db_session, account, date(2028, 1, 31), "1000.00")
    add(db_session, account, date(2028, 2, 1), "1.00")
    add(db_session, account, date(2028, 2, 29), "2.00")
    add(db_session, account, date(2028, 3, 1), "1000.00")

    monthly = get(client, "monthly", "2028-02", "2028-02")
    assert monthly["months"] == [
        {"month": "2028-02", "money_in": "0.00", "money_out": "3.00", "net": "-3.00"}
    ]
    expenses = get(client, "expenses", "2028-02", "2028-02")
    assert expense_amounts(expenses)["other"] == ("3.00", ["3.00"])


@pytest.mark.parametrize("path", ["monthly", "expenses"])
@pytest.mark.parametrize(
    "params",
    [
        {"to": "2026-11"},
        {"from": "2026-11"},
        {"from": "2026-13", "to": "2026-13"},
        {"from": "2026-9", "to": "2026-10"},
        {"from": "abc", "to": "2026-10"},
        {"from": "2026-11", "to": "2026-10"},
        {"from": "2025-01", "to": "2027-01"},
    ],
)
def test_invalid_input_is_422(client: TestClient, path: str, params: dict[str, str]) -> None:
    assert client.get(f"/api/reports/{path}", params=params).status_code == 422


@pytest.mark.parametrize("path", ["monthly", "expenses"])
def test_exactly_24_months_is_accepted(client: TestClient, path: str) -> None:
    body = get(client, path, "2025-01", "2026-12")
    months = body["months"] if path == "monthly" else body["categories"][0]["months"]
    assert len(months) == 24
