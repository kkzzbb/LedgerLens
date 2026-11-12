"""Store bank accounts and imported bank transactions.

Imported transactions are never updated (`docs/accounting-rules.md`, Bank
transactions): a record whose external ID is already stored is skipped. The
only column written after insert is `category` (`categorize_transactions`). No
function here commits; the caller owns the transaction.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from ledgerlens.db.models import BankAccount, BankTransaction
from ledgerlens.domain.categories import CategoryKey, categorize
from ledgerlens.domain.normalization import NormalizedTransaction

CHUNK_SIZE: Final = 1_000


@dataclass(frozen=True)
class InsertResult:
    created_ids: list[int]
    created_count: int
    skipped_count: int


def insert_new_transactions(
    session: Session, account: BankAccount, batch: Sequence[NormalizedTransaction]
) -> InsertResult:
    """Insert the transactions of `batch` not stored yet, in chunks of `CHUNK_SIZE`."""
    for record in batch:
        if record.external_account_id != account.external_account_id:
            raise ValueError("transaction does not belong to the account")
    created_ids: list[int] = []
    for start in range(0, len(batch), CHUNK_SIZE):
        rows = [_row(account, record) for record in batch[start : start + CHUNK_SIZE]]
        statement = (
            insert(BankTransaction)
            .values(rows)
            .on_conflict_do_nothing(index_elements=["provider", "external_transaction_id"])
            .returning(BankTransaction.id)
        )
        created_ids.extend(session.execute(statement).scalars())
    return InsertResult(
        created_ids=created_ids,
        created_count=len(created_ids),
        skipped_count=len(batch) - len(created_ids),
    )


def categorize_transactions(session: Session, bank_account_id: int) -> int:
    """Sets `category` on every transaction of the account where it is NULL.

    Writes only the `category` column. Returns the number of rows categorized.
    """
    rows = session.execute(
        select(
            BankTransaction.id,
            BankTransaction.direction,
            BankTransaction.counterparty_name,
            BankTransaction.description,
        ).where(
            BankTransaction.bank_account_id == bank_account_id,
            BankTransaction.category.is_(None),
        )
    ).all()
    by_category: dict[CategoryKey, list[int]] = {}
    for row in rows:
        key = categorize(row.direction, row.counterparty_name, row.description)
        by_category.setdefault(key, []).append(row.id)
    for key, ids in by_category.items():
        session.execute(
            update(BankTransaction)
            .where(BankTransaction.id.in_(ids))
            .values(category=key)
            .execution_options(synchronize_session=False)
        )
    return len(rows)


def list_bank_accounts(session: Session) -> Sequence[BankAccount]:
    """Every stored account, ordered by `id`. Read-only."""
    return session.scalars(select(BankAccount).order_by(BankAccount.id)).all()


def upsert_bank_account(
    session: Session,
    provider: str,
    external_account_id: str,
    display_name: str,
    currency: str,
) -> BankAccount:
    """Insert the account, or update only `display_name` of the stored one."""
    statement = (
        insert(BankAccount)
        .values(
            provider=provider,
            external_account_id=external_account_id,
            display_name=display_name,
            currency=currency,
        )
        .on_conflict_do_update(
            index_elements=["provider", "external_account_id"],
            set_={"display_name": display_name},
        )
        .returning(BankAccount)
    )
    query = select(BankAccount).from_statement(statement)
    account: BankAccount = session.execute(
        query, execution_options={"populate_existing": True}
    ).scalar_one()
    return account


def _row(account: BankAccount, record: NormalizedTransaction) -> dict[str, object]:
    return {
        "bank_account_id": account.id,
        "provider": account.provider,
        "external_transaction_id": record.external_transaction_id,
        "booking_date": record.booking_date,
        "value_date": record.value_date,
        "amount": record.amount,
        "currency": record.currency,
        "direction": record.direction,
        "counterparty_name": record.counterparty_name,
        "counterparty_reference": record.counterparty_reference,
        "description": record.description,
        "status": record.status,
        "source_metadata": record.source_metadata,
    }
