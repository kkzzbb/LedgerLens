"""Anomaly flags: one per (rule, bank transaction), each a potential issue to review.

A rule can run again after every sync without creating a second flag for the
same transaction. A flag is never a finding about the transaction; a person
marks it `reviewed` once they have looked at it.
"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ledgerlens.db.base import Base
from ledgerlens.db.models.bank import BankTransaction
from ledgerlens.domain.anomalies import RULE_KEYS

RULE_VALID = "rule IN ({})".format(", ".join(f"'{key}'" for key in RULE_KEYS))


class AnomalyFlag(Base):
    __tablename__ = "anomaly_flag"
    __table_args__ = (
        UniqueConstraint("rule", "bank_transaction_id"),
        CheckConstraint(RULE_VALID, name="rule_valid"),
        CheckConstraint("status IN ('open', 'reviewed')", name="status_valid"),
        CheckConstraint(
            "related_transaction_id <> bank_transaction_id", name="related_transaction_differs"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    rule: Mapped[str] = mapped_column(Text)
    # The flagged transaction.
    bank_transaction_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey(BankTransaction.id, ondelete="RESTRICT")
    )
    # For a possible duplicate, the earlier payment.
    related_transaction_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey(BankTransaction.id, ondelete="RESTRICT")
    )
    # A short sentence written by the rule.
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    transaction: Mapped[BankTransaction] = relationship(foreign_keys=[bank_transaction_id])
    related_transaction: Mapped[BankTransaction | None] = relationship(
        foreign_keys=[related_transaction_id]
    )
