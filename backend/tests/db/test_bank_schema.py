"""The bank account and bank transaction tables (migration 0002)."""

from collections.abc import Callable
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from alembic import command
from sqlalchemy import inspect, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ledgerlens.db.models import BankAccount, BankTransaction
from ledgerlens.db.session import make_engine
from tests.db.support import alembic_config

pytestmark = pytest.mark.db


def make_account(**overrides: Any) -> BankAccount:
    values: dict[str, Any] = {
        "provider": "demobank",
        "external_account_id": "acc-1",
        "display_name": "Main account",
        "currency": "EUR",
    }
    return BankAccount(**(values | overrides))


def make_transaction(account: BankAccount, **overrides: Any) -> BankTransaction:
    values: dict[str, Any] = {
        "bank_account_id": account.id,
        "provider": "demobank",
        "external_transaction_id": "tx-1",
        "booking_date": date(2026, 11, 1),
        "value_date": date(2026, 11, 2),
        "amount": Decimal("12.34"),
        "currency": "EUR",
        "direction": "debit",
        "counterparty_name": "Shop",
        "status": "booked",
        "source_metadata": {},
    }
    return BankTransaction(**(values | overrides))


def saved_account(session: Session) -> BankAccount:
    account = make_account()
    session.add(account)
    session.flush()
    return account


def assert_rejected(session: Session, row: object) -> None:
    session.add(row)
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_duplicate_account_is_rejected(db_session: Session) -> None:
    saved_account(db_session)
    assert_rejected(db_session, make_account(display_name="Other name"))


def test_duplicate_transaction_is_rejected(db_session: Session) -> None:
    account = saved_account(db_session)
    db_session.add(make_transaction(account))
    db_session.flush()
    assert_rejected(db_session, make_transaction(account, amount=Decimal("1.00")))


@pytest.mark.parametrize(
    "build",
    [
        lambda session: make_account(currency="USD"),
        lambda session: make_transaction(saved_account(session), currency="USD"),
    ],
    ids=["bank_account", "bank_transaction"],
)
def test_non_eur_currency_is_rejected(
    db_session: Session, build: Callable[[Session], object]
) -> None:
    assert_rejected(db_session, build(db_session))


@pytest.mark.parametrize("amount", [Decimal("0.00"), Decimal("-1.00")])
def test_zero_or_negative_amount_is_rejected(db_session: Session, amount: Decimal) -> None:
    account = saved_account(db_session)
    assert_rejected(db_session, make_transaction(account, amount=amount))


def test_invalid_direction_is_rejected(db_session: Session) -> None:
    account = saved_account(db_session)
    assert_rejected(db_session, make_transaction(account, direction="sideways"))


def test_invalid_last_sync_status_is_rejected(db_session: Session) -> None:
    assert_rejected(db_session, make_account(last_sync_status="pending"))


def test_transaction_for_missing_account_is_rejected(db_session: Session) -> None:
    transaction = make_transaction(make_account())
    transaction.bank_account_id = 999_999_999
    assert_rejected(db_session, transaction)


def test_account_without_sync_has_null_sync_columns(db_session: Session) -> None:
    account = saved_account(db_session)
    db_session.refresh(account)

    assert account.created_at is not None
    for column in inspect(BankAccount).columns:
        if column.key.startswith("last_"):
            assert getattr(account, column.key) is None, column.key


@pytest.mark.parametrize("amount", [Decimal("0.01"), Decimal("999999999999.99")])
def test_amount_round_trips_as_decimal(db_session: Session, amount: Decimal) -> None:
    account = saved_account(db_session)
    db_session.add(make_transaction(account, amount=amount))
    db_session.flush()

    stored = db_session.execute(
        text(
            "SELECT amount FROM ledgerlens.bank_transaction WHERE external_transaction_id = 'tx-1'"
        )
    ).scalar_one()
    assert type(stored) is Decimal
    assert stored == amount


def test_last_balance_accepts_a_negative_value(db_session: Session) -> None:
    db_session.add(make_account(last_balance=Decimal("-250.00")))
    db_session.flush()

    stored = db_session.execute(
        text("SELECT last_balance FROM ledgerlens.bank_account")
    ).scalar_one()
    assert type(stored) is Decimal
    assert stored == Decimal("-250.00")


def test_indexes_exist(db_session: Session) -> None:
    indexes = inspect(db_session.connection()).get_indexes("bank_transaction", schema="ledgerlens")
    columns = {tuple(index["column_names"]) for index in indexes}

    assert ("bank_account_id", "booking_date") in columns
    assert ("counterparty_name",) in columns


def test_downgrade_to_0001_drops_both_tables(empty_database_url: URL) -> None:
    config = alembic_config(empty_database_url)
    command.upgrade(config, "head")
    command.downgrade(config, "0001")

    engine = make_engine(empty_database_url)
    try:
        with engine.connect() as connection:
            tables = inspect(connection).get_table_names(schema="ledgerlens")
    finally:
        engine.dispose()
    assert "bank_account" not in tables
    assert "bank_transaction" not in tables
