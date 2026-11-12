"""`run_sync` (#21) against PostgreSQL, with the fake connector."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import Engine, delete, func, select
from sqlalchemy.orm import Session, sessionmaker

from ledgerlens.connectors.base import ConnectorError
from ledgerlens.db.models import BankAccount, BankTransaction
from ledgerlens.services.sync import run_sync
from tests.unit.test_sync_service import FakeConnector, Step, page, record

pytestmark = pytest.mark.db

NOW = datetime(2026, 11, 12, 10, 0, tzinfo=UTC)


def test_sync_twice_stores_two_pages_once(migrated_engine: Engine) -> None:
    factory = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    pages: list[Step] = [
        page(record("db-t1"), record("db-t2"), cursor="c1", more=True),
        page(record("db-t3"), cursor="c2"),
    ]
    try:
        [first] = run_sync(FakeConnector(pages={"acc-1": pages}), factory, lambda: NOW, 2)
        [second] = run_sync(FakeConnector(), factory, lambda: NOW, 2)

        with factory() as session:
            account = session.scalars(select(BankAccount)).one()
            stored = session.scalar(select(func.count()).select_from(BankTransaction))
        assert (first.status, first.created_count) == ("succeeded", 3)
        assert (second.status, second.created_count) == ("succeeded", 0)
        assert stored == 3
        assert account.last_cursor == "c2"
        assert account.last_balance == Decimal("100.50")
        assert account.last_sync_status == "succeeded"
        assert account.last_successful_sync_at == NOW
    finally:
        with factory() as session, session.begin():
            clear(session)


def clear(session: Session) -> None:
    session.execute(delete(BankTransaction))
    session.execute(delete(BankAccount))


def test_sync_categorizes_new_and_older_rows_once(migrated_engine: Engine) -> None:
    factory = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    pages: list[Step] = [
        page(
            record("cat-1", description="Shop rent 2026-11"),
            record("cat-2", direction="credit", description="Customer payment INV-1"),
            cursor="c1",
        )
    ]
    try:
        run_sync(FakeConnector(pages={"acc-1": pages}), factory, lambda: NOW, 2)
        with factory() as session, session.begin():
            # A row stored before the migration: no category yet.
            old = session.scalars(
                select(BankTransaction).where(BankTransaction.external_transaction_id == "cat-1")
            ).one()
            old.category = None
        first_rows = snapshot(factory)

        run_sync(FakeConnector(), factory, lambda: NOW, 2)
        after_first = snapshot(factory)
        run_sync(FakeConnector(), factory, lambda: NOW, 2)
        after_second = snapshot(factory)

        assert first_rows["cat-2"]["category"] == "revenue"
        assert first_rows["cat-1"]["category"] is None
        assert {key: row["category"] for key, row in after_first.items()} == {
            "cat-1": "rent",
            "cat-2": "revenue",
        }
        # Categorization writes only `category`.
        for key, row in first_rows.items():
            assert {**row, "category": None} == {**after_first[key], "category": None}
        assert after_second == after_first
    finally:
        with factory() as session, session.begin():
            clear(session)


def test_failed_sync_stores_no_rows_and_no_categories(migrated_engine: Engine) -> None:
    factory = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    pages: list[Step] = [
        page(record("fail-1", description="Shop rent"), cursor="c1", more=True),
        ConnectorError("timeout", "the bank did not answer"),
    ]
    try:
        [result] = run_sync(FakeConnector(pages={"acc-1": pages}), factory, lambda: NOW, 1)

        assert result.status == "failed"
        assert snapshot(factory) == {}
    finally:
        with factory() as session, session.begin():
            clear(session)


def snapshot(factory: sessionmaker[Session]) -> dict[str, dict[str, object]]:
    """Every column of every stored transaction, by external ID."""
    with factory() as session:
        rows = session.execute(select(BankTransaction.__table__)).mappings().all()
    return {row["external_transaction_id"]: dict(row) for row in rows}
