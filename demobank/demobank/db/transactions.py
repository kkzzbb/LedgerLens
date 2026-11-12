"""Keyset paging over an account's `demobank_sim` transactions (#11).

Rows are read in `(booking_date, transaction_id)` order through the index
`ix_transactions_account_booking`, strictly after the cursor position.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import Engine, select, tuple_

from demobank.api.cursor import Position
from demobank.db.tables import accounts, transactions


@dataclass(frozen=True)
class StoredTransaction:
    transaction_id: str
    account_id: str
    booking_date: date
    value_date: date
    amount: Decimal
    currency: str
    direction: str
    counterparty_name: str
    counterparty_reference: str | None
    description: str | None
    status: str


@dataclass(frozen=True)
class Page:
    transactions: list[StoredTransaction]
    has_more: bool


def account_exists(engine: Engine, account_id: str) -> bool:
    query = select(accounts.c.account_id).where(accounts.c.account_id == account_id)
    with engine.connect() as connection:
        return connection.execute(query).first() is not None


def transactions_page(engine: Engine, account_id: str, after: Position | None, limit: int) -> Page:
    """Up to `limit` rows after `after` (from the oldest when `None`), plus `has_more`."""
    t = transactions.c
    query = select(transactions).where(t.account_id == account_id)
    if after is not None:
        query = query.where(
            tuple_(t.booking_date, t.transaction_id)
            > tuple_(after.booking_date, after.transaction_id)
        )
    query = query.order_by(t.booking_date, t.transaction_id).limit(limit + 1)
    with engine.connect() as connection:
        rows = [StoredTransaction(**row._asdict()) for row in connection.execute(query)]
    return Page(transactions=rows[:limit], has_more=len(rows) > limit)
