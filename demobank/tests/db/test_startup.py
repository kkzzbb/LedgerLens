"""The database step of the startup on a real PostgreSQL database (#9)."""

import logging
import threading
from collections.abc import Iterator
from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, Engine, func, inspect, select, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import IntegrityError

from demobank.app import StartupError, create_app
from demobank.config import get_settings
from demobank.db import startup
from demobank.db.startup import (
    ADVISORY_LOCK_KEY,
    ANCHOR_AFTER_TODAY,
    DatabaseStartupError,
    Initialisation,
    initialise,
    make_engine,
)
from demobank.db.tables import SCHEMA, SCHEMA_VERSION, accounts, simulation, transactions
from demobank.generator import Account, Transaction, generate

pytestmark = pytest.mark.db

NOW = datetime(2026, 6, 30, 14, 30, tzinfo=UTC)
LATER = datetime(2026, 9, 15, 8, 0, tzinfo=UTC)


def clock_at(moment: datetime) -> startup.Clock:
    return lambda: moment


def start(engine: Engine, *, seed: int = 42, anchor: date | None = None) -> Initialisation:
    return initialise(engine, seed=seed, anchor_date=anchor, clock=clock_at(NOW))


def stored_transactions(connection: Connection) -> list[Transaction]:
    rows = connection.execute(select(transactions).order_by(transactions.c.transaction_id))
    return [Transaction(**row._asdict()) for row in rows]


def stored_simulation(connection: Connection) -> list[dict[str, Any]]:
    return [row._asdict() for row in connection.execute(select(simulation))]


def counts(engine: Engine) -> tuple[int, int, int]:
    with engine.connect() as connection:
        return tuple(  # type: ignore[return-value]
            connection.execute(select(func.count()).select_from(table)).scalar_one()
            for table in (simulation, accounts, transactions)
        )


def schema_exists(engine: Engine) -> bool:
    with engine.connect() as connection:
        return SCHEMA in inspect(connection).get_schema_names()


def test_first_start_stores_the_generated_dataset(engine: Engine) -> None:
    result = start(engine, anchor=date(2026, 6, 30))
    expected = generate(42, date(2026, 6, 30))

    with engine.connect() as connection:
        found = stored_transactions(connection)
        [account] = [Account(**row._asdict()) for row in connection.execute(select(accounts))]
        [row] = stored_simulation(connection)

    assert result.generated is True
    assert result.transaction_count == len(expected.transactions)
    assert found == list(expected.transactions)
    for stored, generated in zip(found, expected.transactions, strict=True):
        assert isinstance(stored.amount, Decimal)
        assert str(stored.amount) == str(generated.amount)
    assert account == expected.account
    assert str(account.opening_balance) == "25000.00"
    assert row == {
        "id": 1,
        "seed": Decimal(42),
        "anchor_date": date(2026, 6, 30),
        "schema_version": SCHEMA_VERSION,
        "generated_at": NOW,
    }


def test_tables_have_the_documented_constraints(engine: Engine) -> None:
    start(engine)

    with engine.connect() as connection:
        inspector = inspect(connection)
        assert sorted(inspector.get_table_names(schema=SCHEMA)) == [
            "accounts",
            "simulation",
            "transactions",
        ]
        amount = next(
            c for c in inspector.get_columns("transactions", schema=SCHEMA) if c["name"] == "amount"
        )
        assert str(amount["type"]) == "NUMERIC(14, 2)"
        indexes = inspector.get_indexes("transactions", schema=SCHEMA)
        assert ["account_id", "booking_date", "transaction_id"] in [
            index["column_names"] for index in indexes
        ]
        [foreign_key] = inspector.get_foreign_keys("transactions", schema=SCHEMA)
        assert foreign_key["referred_table"] == "accounts"
        checks = {
            check["name"]: check["sqltext"]
            for table in ("accounts", "transactions")
            for check in inspector.get_check_constraints(table, schema=SCHEMA)
        }
        assert {
            "accounts_currency_eur",
            "transactions_amount_positive",
            "transactions_direction",
        } <= set(checks)


@pytest.mark.parametrize(
    ("column", "value"),
    [("amount", Decimal("0.00")), ("direction", "refund"), ("currency", "USD")],
)
def test_the_checks_reject_invalid_rows(engine: Engine, column: str, value: object) -> None:
    start(engine)
    row = asdict(generate(42, date(2026, 6, 30)).transactions[0])
    row.update(transaction_id="txn_999999", **{column: value})

    with pytest.raises(IntegrityError, match="violates check constraint"), engine.begin() as c:
        c.execute(transactions.insert(), [row])


def test_second_start_changes_nothing(engine: Engine) -> None:
    start(engine)
    with engine.connect() as connection:
        before = stored_simulation(connection), stored_transactions(connection)
    counts_before = counts(engine)

    result = initialise(engine, seed=42, anchor_date=None, clock=clock_at(LATER))

    with engine.connect() as connection:
        after = stored_simulation(connection), stored_transactions(connection)
    assert result.generated is False
    assert result.transaction_count == counts_before[2]
    assert counts(engine) == counts_before
    assert after == before


def test_anchor_date_unset_uses_the_clock_and_a_later_start_keeps_it(engine: Engine) -> None:
    first = initialise(engine, seed=42, anchor_date=None, clock=clock_at(NOW))
    second = initialise(engine, seed=42, anchor_date=None, clock=clock_at(LATER))

    with engine.connect() as connection:
        [row] = stored_simulation(connection)
        last_day = connection.execute(select(func.max(transactions.c.booking_date))).scalar_one()
    assert first.simulation.anchor_date == date(2026, 6, 30)
    assert second.simulation.anchor_date == date(2026, 6, 30)
    assert row["anchor_date"] == date(2026, 6, 30)
    assert last_day == date(2026, 6, 30)


def test_the_clock_date_is_taken_in_utc(engine: Engine) -> None:
    # 23:30 on 30 June in New York is already 1 July in UTC.
    local = datetime(2026, 6, 30, 23, 30, tzinfo=ZoneInfo("America/New_York"))

    result = initialise(engine, seed=42, anchor_date=None, clock=clock_at(local))

    assert result.simulation.anchor_date == date(2026, 7, 1)


def test_anchor_date_after_today_is_rejected_and_nothing_is_created(engine: Engine) -> None:
    tomorrow = NOW.date() + timedelta(days=1)

    with pytest.raises(DatabaseStartupError) as caught:
        start(engine, anchor=tomorrow)

    assert str(caught.value) == ANCHOR_AFTER_TODAY
    assert not schema_exists(engine)


def test_anchor_date_today_is_accepted(engine: Engine) -> None:
    assert start(engine, anchor=NOW.date()).simulation.anchor_date == NOW.date()


def test_other_seed_or_anchor_on_restart_logs_a_warning_and_keeps_the_data(
    engine: Engine, caplog: pytest.LogCaptureFixture
) -> None:
    start(engine, seed=42, anchor=date(2026, 6, 30))
    before = counts(engine)
    caplog.set_level(logging.INFO, logger="demobank")
    caplog.clear()

    result = start(engine, seed=7, anchor=date(2026, 5, 31))

    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert result.generated is False
    assert result.simulation.seed == 42
    assert counts(engine) == before
    assert len(warnings) == 2
    assert warnings[0].startswith("DEMOBANK_SEED is 7 ")
    assert warnings[1].startswith("DEMOBANK_ANCHOR_DATE is 2026-05-31 ")
    for warning in warnings:
        assert "the stored dataset is kept" in warning
        assert "drop the demobank_sim schema" in warning


def test_same_settings_on_restart_log_no_warning(
    engine: Engine, caplog: pytest.LogCaptureFixture
) -> None:
    start(engine, seed=42, anchor=date(2026, 6, 30))
    caplog.set_level(logging.INFO, logger="demobank")
    caplog.clear()

    start(engine, seed=42, anchor=date(2026, 6, 30))
    start(engine, seed=42, anchor=None)

    assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []


def test_generation_logs_one_info_line(engine: Engine, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="demobank")

    result = start(engine, seed=42, anchor=date(2026, 6, 30))

    lines = [r.getMessage() for r in caplog.records if r.name.startswith("demobank")]
    assert lines == [
        f"DemoBank generated its history: seed 42, anchor date 2026-06-30, "
        f"{result.transaction_count} transactions"
    ]
    assert all(r.levelno == logging.INFO for r in caplog.records if r.name.startswith("demobank"))


def test_failure_halfway_leaves_nothing_and_the_next_start_generates(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    inserted: list[int] = []

    def fail_after_transactions(connection: Connection, stored: object) -> None:
        inserted.append(
            connection.execute(select(func.count()).select_from(transactions)).scalar_one()
        )
        raise RuntimeError("injected failure")

    monkeypatch.setattr(startup, "_insert_simulation", fail_after_transactions)
    with pytest.raises(RuntimeError, match="injected failure"):
        start(engine)
    monkeypatch.undo()

    # The transactions were inserted before the failure, then rolled back.
    assert inserted and inserted[0] > 0
    assert not schema_exists(engine)

    result = start(engine)

    assert result.generated is True
    assert counts(engine) == (1, 1, len(generate(42, NOW.date()).transactions))


def test_two_concurrent_starts_end_with_one_dataset(
    empty_database_url: URL, engine: Engine
) -> None:
    results: list[Initialisation] = []
    errors: list[BaseException] = []
    engines = [make_engine(empty_database_url) for _ in range(2)]

    def run(own: Engine) -> None:
        try:
            results.append(start(own))
        except BaseException as exc:  # reported below
            errors.append(exc)

    threads = [threading.Thread(target=run, args=(own,)) for own in engines]
    try:
        # Hold the lock so both starts are waiting on it at the same time.
        with engine.connect() as holder, holder.begin():
            holder.execute(select(func.pg_advisory_xact_lock(ADVISORY_LOCK_KEY)))
            for thread in threads:
                thread.start()
            waiting = 0
            for _ in range(100):
                waiting = holder.execute(
                    text(
                        "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' "
                        "AND NOT granted AND database = (SELECT oid FROM pg_database "
                        "WHERE datname = current_database())"
                    )
                ).scalar_one()
                if waiting == 2:
                    break
                threading.Event().wait(0.05)
            assert waiting == 2
        for thread in threads:
            thread.join(timeout=60)
    finally:
        for own in engines:
            own.dispose()

    assert errors == []
    assert sorted(r.generated for r in results) == [False, True]
    assert counts(engine) == (1, 1, results[0].transaction_count)


def test_stored_schema_version_that_differs_fails_and_changes_nothing(engine: Engine) -> None:
    start(engine)
    with engine.begin() as connection:
        connection.execute(simulation.update().values(schema_version=SCHEMA_VERSION + 1))
    before = counts(engine)

    with pytest.raises(DatabaseStartupError) as caught:
        start(engine)

    message = str(caught.value)
    assert message == (
        f"The demobank_sim schema has version {SCHEMA_VERSION + 1} but this DemoBank needs "
        f"version {SCHEMA_VERSION}: drop the demobank_sim schema (or run "
        "`docker compose down -v`) and restart DemoBank to regenerate the data"
    )
    assert "\n" not in message
    assert counts(engine) == before
    with engine.connect() as connection:
        assert stored_simulation(connection)[0]["schema_version"] == SCHEMA_VERSION + 1


def test_only_the_demobank_sim_schema_is_touched(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE public.untouched (id int)"))
        connection.execute(text("INSERT INTO public.untouched VALUES (1)"))

    def other_tables() -> list[tuple[str, str]]:
        with engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT table_schema, table_name FROM information_schema.tables "
                    "WHERE table_schema NOT IN ('pg_catalog', 'information_schema', :schema) "
                    "ORDER BY 1, 2"
                ),
                {"schema": SCHEMA},
            )
            return [(row[0], row[1]) for row in rows]

    before = other_tables()

    start(engine)

    assert other_tables() == before == [("public", "untouched")]
    with engine.connect() as connection:
        assert connection.execute(text("SELECT id FROM public.untouched")).all() == [(1,)]


def test_large_seed_is_stored_exactly(engine: Engine) -> None:
    seed = 10**30 + 7

    result = start(engine, seed=seed)

    assert result.simulation.seed == seed
    assert start(engine, seed=seed).simulation.seed == seed


# Through the application's startup


@pytest.fixture
def app_environment(monkeypatch: pytest.MonkeyPatch, empty_database_url: URL) -> Iterator[None]:
    for name in ("DEMOBANK_ADMIN_ENABLED", "DEMOBANK_ADMIN_KEY", "DEMOBANK_ANCHOR_DATE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DEMOBANK_API_KEY", "test-api-key")
    monkeypatch.setenv(
        "DEMOBANK_DATABASE_URL", empty_database_url.render_as_string(hide_password=False)
    )
    monkeypatch.setenv("DEMOBANK_SEED", "1234")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_app_startup_generates_the_dataset(app_environment: None, engine: Engine) -> None:
    with TestClient(create_app()) as client:
        assert client.get("/health").status_code == 200

    with engine.connect() as connection:
        [row] = stored_simulation(connection)
    assert row["seed"] == 1234
    assert row["anchor_date"] == datetime.now(UTC).date()
    assert counts(engine)[2] == len(generate(1234, row["anchor_date"]).transactions)


def test_app_startup_rejects_an_anchor_date_after_today(
    app_environment: None, engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    future = datetime.now(UTC).date() + timedelta(days=2)
    monkeypatch.setenv("DEMOBANK_ANCHOR_DATE", future.isoformat())
    get_settings.cache_clear()

    with pytest.raises(StartupError) as caught, TestClient(create_app()):
        pass

    assert str(caught.value) == ANCHOR_AFTER_TODAY
    assert not schema_exists(engine)
