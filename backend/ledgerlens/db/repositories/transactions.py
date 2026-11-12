"""Read stored bank transactions: filtered, newest first, one page at a time.

Read-only; nothing here writes or commits.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.orm import Session

from ledgerlens.db.models import BankTransaction


@dataclass(frozen=True)
class TransactionFilters:
    account_id: int | None = None
    date_from: date | None = None
    date_to: date | None = None
    direction: str | None = None
    # Case-insensitive substring of the counterparty name or the description.
    q: str | None = None
    # A category key; matches only rows already categorized with it.
    category: str | None = None


@dataclass(frozen=True)
class TransactionPage:
    items: Sequence[BankTransaction]
    # Every row matching the filters, ignoring paging.
    total: int


def list_transactions(
    session: Session, filters: TransactionFilters, limit: int, offset: int
) -> TransactionPage:
    """Matching rows by `booking_date` then `id`, both descending, sliced by `limit`/`offset`."""
    conditions = _conditions(filters)
    total = session.scalar(select(func.count()).select_from(BankTransaction).where(*conditions))
    items = session.scalars(
        select(BankTransaction)
        .where(*conditions)
        .order_by(BankTransaction.booking_date.desc(), BankTransaction.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return TransactionPage(items=items, total=total or 0)


def _conditions(filters: TransactionFilters) -> list[ColumnElement[bool]]:
    conditions: list[ColumnElement[bool]] = []
    if filters.account_id is not None:
        conditions.append(BankTransaction.bank_account_id == filters.account_id)
    if filters.date_from is not None:
        conditions.append(BankTransaction.booking_date >= filters.date_from)
    if filters.date_to is not None:
        conditions.append(BankTransaction.booking_date <= filters.date_to)
    if filters.direction is not None:
        conditions.append(BankTransaction.direction == filters.direction)
    if filters.category is not None:
        conditions.append(BankTransaction.category == filters.category)
    q = (filters.q or "").strip()
    if q:
        # `autoescape` matches `%`, `_` and the escape character literally.
        conditions.append(
            or_(
                BankTransaction.counterparty_name.icontains(q, autoescape=True),
                BankTransaction.description.icontains(q, autoescape=True),
            )
        )
    return conditions
