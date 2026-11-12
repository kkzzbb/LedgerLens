"""Alembic options shared by `migrations/env.py` and the migration tests.

The database holds other schemas (`public`, DemoBank's `demobank_sim`), which
LedgerLens does not own. Alembic only looks at the `ledgerlens` schema, and
keeps its version table there.
"""

from typing import Any, Literal

from ledgerlens.db.base import SCHEMA

VERSION_TABLE_SCHEMA = SCHEMA

_NameType = Literal[
    "schema",
    "table",
    "column",
    "index",
    "unique_constraint",
    "foreign_key_constraint",
]


def include_name(name: str | None, type_: _NameType, parent_names: Any) -> bool:
    """Alembic `include_name` hook: reflect only the `ledgerlens` schema."""
    if type_ == "schema":
        return name == SCHEMA
    return True


def context_options() -> dict[str, Any]:
    """Options for `EnvironmentContext.configure` and `MigrationContext.configure`."""
    return {
        "include_schemas": True,
        "include_name": include_name,
        "version_table_schema": VERSION_TABLE_SCHEMA,
    }
