"""Idempotent bank transaction inserts and the bank account upsert."""

from dataclasses import replace
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from ledgerlens.db.models import BankAccount, BankTransaction
from ledgerlens.db.repositories.bank import insert_new_transactions, upsert_bank_account
from ledgerlens.domain.normalization import NormalizedTransaction

pytestmark = pytest.mark.db


def make_record(external_id: str = "tx-1", **overrides: Any) -> NormalizedTransaction:
    record = NormalizedTransaction(
        external_transaction_id=external_id,
        external_account_id="acc-1",
        booking_date=date(2026, 11, 1),
        value_date=None,
        amount=Decimal("12.34"),
        currency="EUR",
        direction="debit",
        counterparty_name="Shop",
        counterparty_reference=None,
        description=None,
        status="booked",
        source_metadata={"transaction_id": external_id},
    )
    return replace(record, **overrides)


def make_account(session: Session) -> BankAccount:
    return upsert_bank_account(session, "demobank", "acc-1", "Main account", "EUR")


def stored_count(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(BankTransaction)) or 0


def test_same_batch_twice_skips_everything(db_session: Session) -> None:
    account = make_account(db_session)
    batch = [make_record("tx-1"), make_record("tx-2")]

    first = insert_new_transactions(db_session, account, batch)
    second = insert_new_transactions(db_session, account, batch)

    assert first.created_count == 2
    assert first.skipped_count == 0
    assert len(first.created_ids) == 2
    assert second.created_ids == []
    assert second.created_count == 0
    assert second.skipped_count == 2
    assert stored_count(db_session) == 2


def test_duplicate_in_batch_is_inserted_once(db_session: Session) -> None:
    account = make_account(db_session)

    result = insert_new_transactions(db_session, account, [make_record(), make_record()])

    assert (result.created_count, result.skipped_count) == (1, 1)
    assert stored_count(db_session) == 1


def test_changed_record_is_skipped_and_stored_row_unchanged(db_session: Session) -> None:
    account = make_account(db_session)
    insert_new_transactions(db_session, account, [make_record()])

    result = insert_new_transactions(db_session, account, [make_record(amount=Decimal("99.99"))])

    assert (result.created_count, result.skipped_count) == (0, 1)
    assert db_session.scalar(select(BankTransaction.amount)) == Decimal("12.34")


def test_foreign_account_record_raises_before_insert(db_session: Session) -> None:
    account = make_account(db_session)
    batch = [make_record("tx-1"), make_record("tx-2", external_account_id="acc-2")]

    with pytest.raises(ValueError):
        insert_new_transactions(db_session, account, batch)

    assert stored_count(db_session) == 0


def test_source_metadata_is_a_copy(db_session: Session) -> None:
    account = make_account(db_session)
    record = make_record()
    insert_new_transactions(db_session, account, [record])

    record.source_metadata["transaction_id"] = "changed"
    db_session.expire_all()

    stored = db_session.scalar(select(BankTransaction.source_metadata))
    assert stored == {"transaction_id": "tx-1"}


def test_empty_batch_runs_no_query(db_session: Session) -> None:
    account = make_account(db_session)
    statements: list[str] = []

    def record_statement(*args: Any) -> None:
        statements.append(str(args[2]))

    connection = db_session.connection()
    event.listen(connection, "before_cursor_execute", record_statement)
    try:
        result = insert_new_transactions(db_session, account, [])
    finally:
        event.remove(connection, "before_cursor_execute", record_statement)

    assert result.created_ids == []
    assert (result.created_count, result.skipped_count) == (0, 0)
    assert statements == []


def test_first_load_of_5000_records_is_stored(db_session: Session) -> None:
    account = make_account(db_session)
    batch = [make_record(f"tx-{index}") for index in range(5_000)]

    result = insert_new_transactions(db_session, account, batch)

    assert result.created_count == 5_000
    assert len(set(result.created_ids)) == 5_000
    assert stored_count(db_session) == 5_000


def test_rollback_leaves_no_rows(db_session: Session) -> None:
    account = make_account(db_session)
    insert_new_transactions(db_session, account, [make_record()])

    db_session.rollback()

    assert stored_count(db_session) == 0
    assert db_session.scalar(select(func.count()).select_from(BankAccount)) == 0


def test_upsert_inserts_new_account_with_empty_sync_state(db_session: Session) -> None:
    account = make_account(db_session)

    assert account.id is not None
    assert (account.provider, account.external_account_id) == ("demobank", "acc-1")
    assert (account.display_name, account.currency) == ("Main account", "EUR")
    assert account.last_cursor is None
    assert account.last_balance is None
    assert account.last_balance_at is None
    assert account.last_sync_at is None
    assert account.last_sync_status is None
    assert account.last_sync_error is None
    assert account.last_successful_sync_at is None


def test_upsert_updates_only_display_name_and_keeps_cursor(db_session: Session) -> None:
    account = make_account(db_session)
    account.last_cursor = "cursor-1"
    db_session.flush()

    again = upsert_bank_account(db_session, "demobank", "acc-1", "Renamed", "EUR")

    assert again.id == account.id
    assert again.display_name == "Renamed"
    assert again.last_cursor == "cursor-1"
    assert db_session.scalar(select(func.count()).select_from(BankAccount)) == 1
