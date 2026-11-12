"""`flag_possible_duplicates` (#28) against PostgreSQL."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from ledgerlens.db.models import AnomalyFlag
from ledgerlens.db.repositories.anomalies import flag_possible_duplicates
from tests.db.test_transactions_api import add, add_account

pytestmark = pytest.mark.db

TODAY = date(2026, 11, 12)


def run(session: Session) -> int:
    return flag_possible_duplicates(session, TODAY, 7, 3, Decimal("1"))


def flags(session: Session) -> list[tuple[str, int, int | None]]:
    return [
        (f.rule, f.bank_transaction_id, f.related_transaction_id)
        for f in session.scalars(select(AnomalyFlag).order_by(AnomalyFlag.id))
    ]


def test_the_window_starts_6_days_before_today(db_session: Session) -> None:
    account = add_account(db_session, "acc-duplicates")

    def debit(days_ago: int) -> int:
        row = add(
            db_session,
            account,
            booking_date=TODAY - timedelta(days=days_ago),
            amount=Decimal("455.00"),
            counterparty_name="Sparkvale Cleaning",
        )
        return row.id

    history = debit(7)  # history only: never flagged
    candidate = debit(6)  # the first candidate day

    assert run(db_session) == 1
    assert flags(db_session) == [("possible_duplicate", candidate, history)]


def test_a_second_run_inserts_nothing(db_session: Session) -> None:
    account = add_account(db_session, "acc-rerun")
    for _ in range(2):
        add(db_session, account, booking_date=TODAY, counterparty_name="Sparkvale Cleaning")

    assert run(db_session) == 1
    assert run(db_session) == 0


def test_an_empty_database_inserts_nothing(db_session: Session) -> None:
    assert run(db_session) == 0
