"""`GET /api/transactions` (#23) against PostgreSQL."""

import itertools
from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from ledgerlens.api import transactions as transactions_api
from ledgerlens.api.app import create_app
from ledgerlens.db.models import BankAccount, BankTransaction

pytestmark = pytest.mark.db

_ids = itertools.count(1)


@pytest.fixture
def client(db_session: Session) -> TestClient:
    """The API reading through a session on the test's rolled-back connection."""
    app = create_app()

    def factory() -> Session:
        return Session(bind=db_session.connection(), join_transaction_mode="create_savepoint")

    app.dependency_overrides[transactions_api.get_session_factory] = lambda: factory
    return TestClient(app)


@pytest.fixture
def account(db_session: Session) -> Iterator[BankAccount]:
    yield add_account(db_session, "acc-1")


def add_account(session: Session, external_id: str) -> BankAccount:
    account = BankAccount(
        provider="demobank", external_account_id=external_id, display_name="A", currency="EUR"
    )
    session.add(account)
    session.flush()
    return account


def add(session: Session, account: BankAccount, **fields: Any) -> BankTransaction:
    values: dict[str, Any] = {
        "booking_date": date(2026, 11, 1),
        "amount": Decimal("10.00"),
        "direction": "debit",
        "status": "booked",
    } | fields
    row = BankTransaction(
        bank_account_id=account.id,
        provider="demobank",
        external_transaction_id=f"t-{next(_ids)}",
        currency="EUR",
        source_metadata={"secret": 1.5},
        **values,
    )
    session.add(row)
    session.flush()
    return row


def get(client: TestClient, **params: Any) -> dict[str, Any]:
    response = client.get("/api/transactions", params=params)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def ids(body: dict[str, Any]) -> list[int]:
    return [item["id"] for item in body["items"]]


def walk(value: object) -> Iterator[object]:
    yield value
    if isinstance(value, dict):
        for item in value.values():
            yield from walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from walk(item)


def test_empty_database(client: TestClient) -> None:
    assert get(client) == {"items": [], "total": 0, "limit": 50, "offset": 0}


def test_item_shape_and_exact_amounts(
    client: TestClient, db_session: Session, account: BankAccount
) -> None:
    row = add(
        db_session,
        account,
        amount=Decimal("1234.5"),
        value_date=date(2026, 11, 2),
        counterparty_name="Shop",
        counterparty_reference="REF",
        description="Paper",
        category="supplier_other",
    )
    add(db_session, account, amount=Decimal("5"), booking_date=date(2026, 10, 1))

    body = get(client)

    assert body["items"][0] == {
        "id": row.id,
        "account_id": account.id,
        "booking_date": "2026-11-01",
        "value_date": "2026-11-02",
        "amount": "1234.50",
        "currency": "EUR",
        "direction": "debit",
        "counterparty_name": "Shop",
        "counterparty_reference": "REF",
        "description": "Paper",
        "status": "booked",
        "category": "supplier_other",
    }
    assert body["items"][1]["amount"] == "5.00"
    assert body["items"][1]["category"] is None
    assert body["items"][1]["value_date"] is None
    assert not any(isinstance(value, float) for value in walk(body))


def test_order_and_paging_split_same_date(
    client: TestClient, db_session: Session, account: BankAccount
) -> None:
    old = add(db_session, account, booking_date=date(2026, 10, 1))
    first = add(db_session, account)
    second = add(db_session, account)

    page_one = get(client, limit=1)
    page_two = get(client, limit=1, offset=1)
    page_three = get(client, limit=1, offset=2)

    assert ids(page_one) + ids(page_two) + ids(page_three) == [second.id, first.id, old.id]
    assert page_two["total"] == 3
    assert (page_two["limit"], page_two["offset"]) == (1, 1)
    assert get(client, offset=10) == {"items": [], "total": 3, "limit": 50, "offset": 10}


@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": 201},
        {"offset": -1},
        {"date_from": "2026-11-02", "date_to": "2026-11-01"},
        {"date_from": "2026-13-01"},
        {"date_to": "nope"},
        {"direction": "both"},
        {"category": "groceries"},
    ],
)
def test_invalid_parameters_return_422(client: TestClient, params: dict[str, Any]) -> None:
    assert client.get("/api/transactions", params=params).status_code == 422


def test_limit_bounds_are_accepted(client: TestClient) -> None:
    assert get(client, limit=1)["limit"] == 1
    assert get(client, limit=200)["limit"] == 200


def test_account_filter(client: TestClient, db_session: Session, account: BankAccount) -> None:
    other = add_account(db_session, "acc-2")
    mine = add(db_session, account)
    add(db_session, other)

    assert ids(get(client, account_id=account.id)) == [mine.id]
    assert get(client, account_id=999_999) == {"items": [], "total": 0, "limit": 50, "offset": 0}


def test_date_bounds_are_inclusive(
    client: TestClient, db_session: Session, account: BankAccount
) -> None:
    rows = {
        day: add(db_session, account, booking_date=date(2026, 11, day)).id for day in range(1, 7)
    }

    body = get(client, date_from="2026-11-02", date_to="2026-11-05")

    assert ids(body) == [rows[5], rows[4], rows[3], rows[2]]
    assert body["total"] == 4
    assert ids(get(client, date_from="2026-11-05")) == [rows[6], rows[5]]
    assert ids(get(client, date_to="2026-11-02")) == [rows[2], rows[1]]


def test_direction_filter(client: TestClient, db_session: Session, account: BankAccount) -> None:
    debit = add(db_session, account, direction="debit")
    credit = add(db_session, account, direction="credit")

    assert ids(get(client, direction="debit")) == [debit.id]
    assert ids(get(client, direction="credit")) == [credit.id]


def test_q_matches_name_or_description_case_insensitively(
    client: TestClient, db_session: Session, account: BankAccount
) -> None:
    by_name = add(db_session, account, counterparty_name="ACME GmbH")
    by_description = add(db_session, account, description="paid acme invoice")
    add(db_session, account, counterparty_name="Other", description="Other")

    assert sorted(ids(get(client, q="Acme"))) == sorted([by_name.id, by_description.id])


def test_q_wildcards_are_literal(
    client: TestClient, db_session: Session, account: BankAccount
) -> None:
    percent = add(db_session, account, description="Discount 10% off")
    underscore = add(db_session, account, description="a_b")
    backslash = add(db_session, account, description="C:\\x")
    add(db_session, account, description="Discount 100 off, axb, C:x")

    assert ids(get(client, q="10%")) == [percent.id]
    assert ids(get(client, q="a_b")) == [underscore.id]
    assert ids(get(client, q="\\")) == [backslash.id]


def test_blank_q_is_ignored(client: TestClient, db_session: Session, account: BankAccount) -> None:
    add(db_session, account)

    assert get(client, q="")["total"] == 1
    assert get(client, q="   ")["total"] == 1


def test_filters_combine_with_and(
    client: TestClient, db_session: Session, account: BankAccount
) -> None:
    other = add_account(db_session, "acc-2")
    match = add(db_session, account, direction="credit", description="Rent")
    add(db_session, account, direction="debit", description="Rent")
    elsewhere = add(db_session, other, direction="credit", description="Rent")
    add(db_session, account, direction="credit", description="Rent", booking_date=date(2026, 9, 1))

    assert get(client, account_id=account.id, direction="credit")["total"] == 2
    assert ids(get(client, direction="credit", q="rent", date_from="2026-10-01")) == [
        elsewhere.id,
        match.id,
    ]
    assert ids(get(client, account_id=account.id, direction="credit", date_from="2026-10-01")) == [
        match.id
    ]


def test_category_filter_combines_with_the_other_filters(
    client: TestClient, db_session: Session, account: BankAccount
) -> None:
    rent = add(db_session, account, category="rent", description="Shop rent")
    add(db_session, account, category="rent", booking_date=date(2026, 10, 1))
    add(db_session, account, category="software", description="Shop rent")
    add(db_session, account)

    assert get(client, category="rent")["total"] == 2
    assert ids(get(client, category="rent", date_from="2026-11-01", q="shop")) == [rent.id]
    assert get(client, category="other")["total"] == 0
