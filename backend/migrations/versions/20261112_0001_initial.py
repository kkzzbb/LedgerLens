"""Initial migration: the ledgerlens schema.

Revision ID: 0001
Revises:
Create Date: 2026-11-12
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # env.py already created the schema (it holds alembic_version); repeated
    # here so the migration describes the schema on its own.
    op.execute("CREATE SCHEMA IF NOT EXISTS ledgerlens")


def downgrade() -> None:
    # The schema holds alembic_version, so a migration cannot drop it.
    pass
