"""Sums of stored bank transactions per month, for the reports.

Read-only; nothing here writes or commits. Every account and every `status`
counts. Months are `YYYY-MM` strings of `booking_date`.
"""

from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ledgerlens.db.models import BankTransaction
from ledgerlens.domain.categories import OTHER

_MONTH = func.to_char(BankTransaction.booking_date, "YYYY-MM")


def sums_by_month_and_direction(
    session: Session, first_day: date, last_day: date
) -> dict[tuple[str, str], Decimal]:
    """`(month, direction)` -> sum of `amount`, booked from `first_day` to `last_day`."""
    rows = session.execute(
        select(_MONTH, BankTransaction.direction, func.sum(BankTransaction.amount))
        .where(BankTransaction.booking_date >= first_day, BankTransaction.booking_date <= last_day)
        .group_by(_MONTH, BankTransaction.direction)
    ).all()
    return {(month, direction): total for month, direction, total in rows}


def debit_sums_by_category_and_month(
    session: Session, first_day: date, last_day: date
) -> dict[tuple[str, str], Decimal]:
    """`(category, month)` -> sum of debit `amount`; a null category counts as `other`."""
    category = func.coalesce(BankTransaction.category, OTHER)
    rows = session.execute(
        select(category, _MONTH, func.sum(BankTransaction.amount))
        .where(
            BankTransaction.direction == "debit",
            BankTransaction.booking_date >= first_day,
            BankTransaction.booking_date <= last_day,
        )
        .group_by(category, _MONTH)
    ).all()
    return {(key, month): total for key, month, total in rows}
