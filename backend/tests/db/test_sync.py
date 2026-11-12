"""`run_sync` (#21) against PostgreSQL, with the fake connector."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import Engine, delete, func, select
from sqlalchemy.orm import Session, sessionmaker

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
