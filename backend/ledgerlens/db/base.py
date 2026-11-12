"""The declarative base every LedgerLens model inherits from.

Every table lands in the `ledgerlens` schema, and every constraint and index
gets a stable name from the naming convention below, so that migrations can
refer to them by name.
"""

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

SCHEMA = "ledgerlens"

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Base class of the LedgerLens models."""

    metadata = MetaData(schema=SCHEMA, naming_convention=NAMING_CONVENTION)
