"""The category of a bank transaction.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "ledgerlens"
TABLE = "bank_transaction"

CONSTRAINTS = {
    "category_valid": (
        "category IN ('revenue', 'rent', 'software', 'utilities', 'inventory', "
        "'supplier_other', 'other')"
    ),
    "category_credit": "direction <> 'credit' OR category IN ('revenue', 'other')",
    "category_debit": "direction <> 'debit' OR category <> 'revenue'",
}


def upgrade() -> None:
    op.add_column(TABLE, sa.Column("category", sa.Text(), nullable=True), schema=SCHEMA)
    for name, condition in CONSTRAINTS.items():
        op.create_check_constraint(op.f(f"ck_{TABLE}_{name}"), TABLE, condition, schema=SCHEMA)


def downgrade() -> None:
    op.drop_column(TABLE, "category", schema=SCHEMA)
