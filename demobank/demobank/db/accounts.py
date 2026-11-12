"""Read queries on the `demobank_sim` accounts and their balances (#10).

The balance is read from the stored transactions at every call, never cached,
so it always agrees with them (#12 appends rows).
"""

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import Engine, ScalarSelect, func, select

from demobank.db.tables import accounts, transactions


@dataclass(frozen=True)
class AccountSummary:
    account_id: str
    display_name: str
    currency: str


@dataclass(frozen=True)
class Balance:
    account_id: str
    balance: Decimal
    currency: str


def list_accounts(engine: Engine) -> list[AccountSummary]:
    """Every account, ordered by `account_id`."""
    query = select(accounts.c.account_id, accounts.c.display_name, accounts.c.currency).order_by(
        accounts.c.account_id
    )
    with engine.connect() as connection:
        return [AccountSummary(**row._asdict()) for row in connection.execute(query)]


def _sum_of(account_id: str, direction: str) -> ScalarSelect[Decimal]:
    """The sum of the account's amounts in one direction, 0 when there is none."""
    return (
        select(func.coalesce(func.sum(transactions.c.amount), 0))
        .where(transactions.c.account_id == account_id, transactions.c.direction == direction)
        .scalar_subquery()
    )


def account_balance(engine: Engine, account_id: str) -> Balance | None:
    """Opening balance + credits - debits over every stored row; `None` if unknown."""
    credits = _sum_of(account_id, "credit")
    debits = _sum_of(account_id, "debit")
    query = select(accounts.c.opening_balance, accounts.c.currency, credits, debits).where(
        accounts.c.account_id == account_id
    )
    with engine.connect() as connection:
        row = connection.execute(query).one_or_none()
    if row is None:
        return None
    opening, currency, credit_sum, debit_sum = row
    balance = Decimal(opening) + Decimal(credit_sum) - Decimal(debit_sum)
    return Balance(account_id=account_id, balance=balance, currency=currency)
