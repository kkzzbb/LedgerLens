"""Anomaly flags.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "ledgerlens"


def upgrade() -> None:
    op.create_table(
        "anomaly_flag",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("rule", sa.Text(), nullable=False),
        sa.Column("bank_transaction_id", sa.BigInteger(), nullable=False),
        sa.Column("related_transaction_id", sa.BigInteger(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default="open", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_anomaly_flag")),
        sa.UniqueConstraint("rule", "bank_transaction_id", name=op.f("uq_anomaly_flag_rule")),
        sa.CheckConstraint(
            "rule IN ('possible_duplicate', 'large_expense')",
            name=op.f("ck_anomaly_flag_rule_valid"),
        ),
        sa.CheckConstraint(
            "status IN ('open', 'reviewed')", name=op.f("ck_anomaly_flag_status_valid")
        ),
        sa.CheckConstraint(
            "related_transaction_id <> bank_transaction_id",
            name=op.f("ck_anomaly_flag_related_transaction_differs"),
        ),
        sa.ForeignKeyConstraint(
            ["bank_transaction_id"],
            [f"{SCHEMA}.bank_transaction.id"],
            name=op.f("fk_anomaly_flag_bank_transaction_id_bank_transaction"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["related_transaction_id"],
            [f"{SCHEMA}.bank_transaction.id"],
            name=op.f("fk_anomaly_flag_related_transaction_id_bank_transaction"),
            ondelete="RESTRICT",
        ),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_table("anomaly_flag", schema=SCHEMA)
