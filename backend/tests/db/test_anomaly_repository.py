"""`anomaly_flag` storage and `insert_flags` (#27) against PostgreSQL."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ledgerlens.db.models import AnomalyFlag, BankAccount, BankTransaction
from ledgerlens.db.repositories.anomalies import NewFlag, insert_flags
from tests.db.test_transactions_api import add, add_account

pytestmark = pytest.mark.db


@pytest.fixture
def rows(db_session: Session) -> list[BankTransaction]:
    account: BankAccount = add_account(db_session, "acc-anomaly")
    return [add(db_session, account) for _ in range(3)]


def count(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(AnomalyFlag)) or 0


def test_the_same_rule_and_transaction_twice_fails_at_the_database(
    db_session: Session, rows: list[BankTransaction]
) -> None:
    db_session.add(AnomalyFlag(rule="large_expense", bank_transaction_id=rows[0].id, reason="a"))
    db_session.flush()
    db_session.add(AnomalyFlag(rule="large_expense", bank_transaction_id=rows[0].id, reason="b"))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_inserting_twice_returns_n_then_zero(
    db_session: Session, rows: list[BankTransaction]
) -> None:
    flags = [
        NewFlag("possible_duplicate", rows[1].id, rows[0].id, "Same amount"),
        NewFlag("large_expense", rows[2].id, None, "Large"),
    ]

    assert insert_flags(db_session, flags) == 2
    assert insert_flags(db_session, flags) == 0
    assert count(db_session) == 2


def test_a_reinsert_does_not_change_a_reviewed_flag(
    db_session: Session, rows: list[BankTransaction]
) -> None:
    created = datetime(2026, 1, 1, tzinfo=UTC)
    reviewed = datetime(2026, 1, 2, tzinfo=UTC)
    flag = AnomalyFlag(
        rule="large_expense",
        bank_transaction_id=rows[0].id,
        reason="Original",
        status="reviewed",
        created_at=created,
        reviewed_at=reviewed,
    )
    db_session.add(flag)
    db_session.flush()

    assert insert_flags(db_session, [NewFlag("large_expense", rows[0].id, None, "New")]) == 0

    db_session.refresh(flag)
    assert (flag.status, flag.reason, flag.created_at, flag.reviewed_at) == (
        "reviewed",
        "Original",
        created,
        reviewed,
    )


def test_the_same_pair_twice_in_one_call_inserts_one_row(
    db_session: Session, rows: list[BankTransaction]
) -> None:
    flag = NewFlag("large_expense", rows[0].id, None, "Large")

    assert insert_flags(db_session, [flag, flag]) == 1
    assert count(db_session) == 1


def test_an_empty_list_returns_zero(db_session: Session) -> None:
    assert insert_flags(db_session, []) == 0


def test_one_transaction_can_carry_both_rules(
    db_session: Session, rows: list[BankTransaction]
) -> None:
    flags = [
        NewFlag("possible_duplicate", rows[1].id, rows[0].id, "Same amount"),
        NewFlag("large_expense", rows[1].id, None, "Large"),
    ]

    assert insert_flags(db_session, flags) == 2
    assert count(db_session) == 2
