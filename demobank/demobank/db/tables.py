"""The tables of the `demobank_sim` schema, created with `metadata.create_all`.

There is no Alembic: the data can be regenerated from the seed and the anchor
date, so a schema from another version fails startup loudly instead of being
migrated. `SCHEMA_VERSION` is bumped by every change to a table (#12, #13).
"""

from sqlalchemy import (
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    SmallInteger,
    String,
    Table,
)

SCHEMA = "demobank_sim"
SCHEMA_VERSION = 1

metadata = MetaData(schema=SCHEMA)

# One row: the seed and anchor date the stored dataset was generated with.
simulation = Table(
    "simulation",
    metadata,
    Column("id", SmallInteger, primary_key=True, autoincrement=False),
    # Unbounded NUMERIC: DEMOBANK_SEED is any non-negative integer.
    Column("seed", Numeric(asdecimal=True), nullable=False),
    Column("anchor_date", Date, nullable=False),
    Column("schema_version", Integer, nullable=False),
    Column("generated_at", DateTime(timezone=True), nullable=False),
    CheckConstraint("id = 1", name="simulation_one_row"),
    CheckConstraint("seed >= 0 AND seed = trunc(seed)", name="simulation_seed_non_negative"),
)

accounts = Table(
    "accounts",
    metadata,
    Column("account_id", String(64), primary_key=True),
    Column("display_name", String(200), nullable=False),
    Column("currency", String(3), nullable=False),
    Column("opening_balance", Numeric(14, 2), nullable=False),
    CheckConstraint("currency = 'EUR'", name="accounts_currency_eur"),
)

transactions = Table(
    "transactions",
    metadata,
    Column("transaction_id", String(32), primary_key=True),
    Column(
        "account_id",
        String(64),
        ForeignKey(accounts.c.account_id, name="transactions_account_id_fkey"),
        nullable=False,
    ),
    Column("booking_date", Date, nullable=False),
    Column("value_date", Date, nullable=False),
    Column("amount", Numeric(14, 2), nullable=False),
    Column("currency", String(3), nullable=False),
    Column("direction", String(6), nullable=False),
    Column("counterparty_name", String(200), nullable=False),
    Column("counterparty_reference", String(64)),
    Column("description", String(500)),
    Column("status", String(16), nullable=False),
    CheckConstraint("amount > 0", name="transactions_amount_positive"),
    CheckConstraint("currency = 'EUR'", name="transactions_currency_eur"),
    CheckConstraint("direction IN ('debit', 'credit')", name="transactions_direction"),
    # #11 pages through an account's transactions in this order.
    Index("ix_transactions_account_booking", "account_id", "booking_date", "transaction_id"),
)
