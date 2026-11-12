"""Synced bank accounts and their imported bank transactions.

The account row is the only sync record: it holds the cursor, the balance and
the last sync time and result. Transaction columns follow DemoBank's
transaction shape; the imported facts are never updated after insert
(`docs/accounting-rules.md`, Bank transactions). `category` is the only column
written after insert, by the categorization rules (#25).
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CHAR,
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Numeric,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ledgerlens.db.base import Base

MONEY = Numeric(14, 2)

# The keys of `ledgerlens.domain.categories.CATEGORIES`. A credit is `revenue`
# or `other`; a debit is anything but `revenue` (`docs/accounting-rules.md`).
CATEGORY_VALID = (
    "category IN ('revenue', 'rent', 'software', 'utilities', 'inventory', "
    "'supplier_other', 'other')"
)
CATEGORY_CREDIT = "direction <> 'credit' OR category IN ('revenue', 'other')"
CATEGORY_DEBIT = "direction <> 'debit' OR category <> 'revenue'"


class BankAccount(Base):
    __tablename__ = "bank_account"
    __table_args__ = (
        UniqueConstraint("provider", "external_account_id"),
        CheckConstraint("currency = 'EUR'", name="currency_eur"),
        CheckConstraint(
            "last_sync_status IN ('succeeded', 'succeeded_with_errors', 'failed')",
            name="last_sync_status_valid",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    provider: Mapped[str] = mapped_column(Text)
    external_account_id: Mapped[str] = mapped_column(Text)
    display_name: Mapped[str] = mapped_column(Text)
    currency: Mapped[str] = mapped_column(CHAR(3))
    last_cursor: Mapped[str | None] = mapped_column(Text)
    last_balance: Mapped[Decimal | None] = mapped_column(MONEY)
    last_balance_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_sync_status: Mapped[str | None] = mapped_column(Text)
    # A short classified message, never raw field values, secrets or bodies.
    last_sync_error: Mapped[str | None] = mapped_column(Text)
    last_successful_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BankTransaction(Base):
    __tablename__ = "bank_transaction"
    __table_args__ = (
        UniqueConstraint("provider", "external_transaction_id"),
        CheckConstraint("currency = 'EUR'", name="currency_eur"),
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint("direction IN ('debit', 'credit')", name="direction_valid"),
        CheckConstraint(CATEGORY_VALID, name="category_valid"),
        CheckConstraint(CATEGORY_CREDIT, name="category_credit"),
        CheckConstraint(CATEGORY_DEBIT, name="category_debit"),
        Index(None, "bank_account_id", "booking_date"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    bank_account_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey(BankAccount.id, ondelete="RESTRICT")
    )
    provider: Mapped[str] = mapped_column(Text)
    external_transaction_id: Mapped[str] = mapped_column(Text)
    booking_date: Mapped[date] = mapped_column(Date)
    value_date: Mapped[date | None] = mapped_column(Date)
    # Always positive; `direction` carries the sign.
    amount: Mapped[Decimal] = mapped_column(MONEY)
    currency: Mapped[str] = mapped_column(CHAR(3))
    direction: Mapped[str] = mapped_column(Text)
    counterparty_name: Mapped[str | None] = mapped_column(Text, index=True)
    counterparty_reference: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    source_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB)
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # A `CATEGORIES` key set by the rules; NULL until the next sync categorizes the row.
    category: Mapped[str | None] = mapped_column(Text)
