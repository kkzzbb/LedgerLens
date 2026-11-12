"""Bank accounts and bank transactions.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "ledgerlens"


def upgrade() -> None:
    op.create_table(
        "bank_account",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("external_account_id", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("currency", sa.CHAR(3), nullable=False),
        sa.Column("last_cursor", sa.Text(), nullable=True),
        sa.Column("last_balance", sa.Numeric(14, 2), nullable=True),
        sa.Column("last_balance_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_status", sa.Text(), nullable=True),
        sa.Column("last_sync_error", sa.Text(), nullable=True),
        sa.Column("last_successful_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_bank_account")),
        sa.UniqueConstraint(
            "provider", "external_account_id", name=op.f("uq_bank_account_provider")
        ),
        sa.CheckConstraint("currency = 'EUR'", name=op.f("ck_bank_account_currency_eur")),
        sa.CheckConstraint(
            "last_sync_status IN ('succeeded', 'succeeded_with_errors', 'failed')",
            name=op.f("ck_bank_account_last_sync_status_valid"),
        ),
        schema=SCHEMA,
    )
    op.create_table(
        "bank_transaction",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("bank_account_id", sa.BigInteger(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("external_transaction_id", sa.Text(), nullable=False),
        sa.Column("booking_date", sa.Date(), nullable=False),
        sa.Column("value_date", sa.Date(), nullable=True),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("currency", sa.CHAR(3), nullable=False),
        sa.Column("direction", sa.Text(), nullable=False),
        sa.Column("counterparty_name", sa.Text(), nullable=True),
        sa.Column("counterparty_reference", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("source_metadata", postgresql.JSONB(), nullable=False),
        sa.Column(
            "imported_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_bank_transaction")),
        sa.UniqueConstraint(
            "provider",
            "external_transaction_id",
            name=op.f("uq_bank_transaction_provider"),
        ),
        sa.CheckConstraint("currency = 'EUR'", name=op.f("ck_bank_transaction_currency_eur")),
        sa.CheckConstraint("amount > 0", name=op.f("ck_bank_transaction_amount_positive")),
        sa.CheckConstraint(
            "direction IN ('debit', 'credit')",
            name=op.f("ck_bank_transaction_direction_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["bank_account_id"],
            [f"{SCHEMA}.bank_account.id"],
            name=op.f("fk_bank_transaction_bank_account_id_bank_account"),
            ondelete="RESTRICT",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        op.f("ix_ledgerlens_bank_transaction_bank_account_id"),
        "bank_transaction",
        ["bank_account_id", "booking_date"],
        schema=SCHEMA,
    )
    op.create_index(
        op.f("ix_ledgerlens_bank_transaction_counterparty_name"),
        "bank_transaction",
        ["counterparty_name"],
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_table("bank_transaction", schema=SCHEMA)
    op.drop_table("bank_account", schema=SCHEMA)
