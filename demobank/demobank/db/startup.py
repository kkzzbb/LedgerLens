"""The database step of DemoBank's startup: generate the history once (#9).

When the `simulation` table has no row, `initialise` generates the dataset
and stores it, in one database transaction under a PostgreSQL advisory lock,
so two DemoBank processes starting at the same time end with one dataset.
When the row exists, nothing is generated or changed: the stored seed and
anchor date stay in force, so a restart never shifts the data.

Only this module reads the clock, through the injectable `clock`. No error
message or log line contains the database URL or its password.
"""

import logging
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import Connection, Engine, create_engine, func, inspect, select
from sqlalchemy.engine import URL
from sqlalchemy.exc import DBAPIError, SQLAlchemyError
from sqlalchemy.schema import CreateSchema

from demobank.config import Settings
from demobank.db.tables import (
    SCHEMA,
    SCHEMA_VERSION,
    accounts,
    metadata,
    simulation,
    transactions,
)
from demobank.db.url import database_url
from demobank.generator import Dataset, generate

logger = logging.getLogger(__name__)

Clock = Callable[[], datetime]

# Seconds libpq waits for a connection to be established, as in the backend (#6).
CONNECT_TIMEOUT_SECONDS = 5
# The key of the transaction-level advisory lock: "DEMOBANK" in ASCII.
ADVISORY_LOCK_KEY = 0x44454D4F42414E4B

CANNOT_CONNECT = "DemoBank cannot connect to the database (DEMOBANK_DATABASE_URL)"
ANCHOR_AFTER_TODAY = "DEMOBANK_ANCHOR_DATE must not be after today"
REGENERATE = "drop the demobank_sim schema (or run `docker compose down -v`) and restart DemoBank"


class DatabaseStartupError(Exception):
    """DemoBank cannot prepare its database. The message is one line, without the URL."""


@dataclass(frozen=True)
class StoredSimulation:
    seed: int
    anchor_date: date
    schema_version: int
    generated_at: datetime


@dataclass(frozen=True)
class Initialisation:
    """What startup found or did."""

    simulation: StoredSimulation
    generated: bool  # False when a stored dataset was kept
    transaction_count: int


def utc_now() -> datetime:
    """The real clock: the current time in UTC."""
    return datetime.now(UTC)


def make_engine(url: str | URL, *, connect_timeout: int = CONNECT_TIMEOUT_SECONDS) -> Engine:
    """An engine for `url` with the psycopg 3 driver and a connect timeout."""
    return create_engine(
        database_url(url),
        pool_pre_ping=True,
        echo=False,
        connect_args={"connect_timeout": connect_timeout},
    )


def _connect(engine: Engine) -> Connection:
    try:
        return engine.connect()
    except DBAPIError:
        pass
    # Outside the `except` block: the driver error is not chained.
    raise DatabaseStartupError(CANNOT_CONNECT)


def _stored_simulation(connection: Connection) -> StoredSimulation | None:
    if not inspect(connection).has_table(simulation.name, schema=SCHEMA):
        return None
    # The version is read on its own: the other columns may differ in another version.
    version = connection.execute(select(simulation.c.schema_version)).scalar_one_or_none()
    if version is None:
        return None
    if version != SCHEMA_VERSION:
        raise DatabaseStartupError(
            f"The demobank_sim schema has version {version} but this DemoBank needs "
            f"version {SCHEMA_VERSION}: {REGENERATE} to regenerate the data"
        )
    row = connection.execute(select(simulation)).one()
    return StoredSimulation(
        seed=int(row.seed),
        anchor_date=row.anchor_date,
        schema_version=row.schema_version,
        generated_at=row.generated_at,
    )


def _warn_about_ignored_settings(
    stored: StoredSimulation, seed: int, anchor_date: date | None
) -> None:
    if seed != stored.seed:
        logger.warning(
            "DEMOBANK_SEED is %s but the stored dataset was generated with seed %s: "
            "the stored dataset is kept. To regenerate it, %s",
            seed,
            stored.seed,
            REGENERATE,
        )
    if anchor_date is not None and anchor_date != stored.anchor_date:
        logger.warning(
            "DEMOBANK_ANCHOR_DATE is %s but the stored dataset was generated with anchor "
            "date %s: the stored dataset is kept. To regenerate it, %s",
            anchor_date.isoformat(),
            stored.anchor_date.isoformat(),
            REGENERATE,
        )


def _insert_dataset(connection: Connection, dataset: Dataset) -> None:
    connection.execute(accounts.insert(), [asdict(dataset.account)])
    connection.execute(transactions.insert(), [asdict(t) for t in dataset.transactions])


def _insert_simulation(connection: Connection, stored: StoredSimulation) -> None:
    connection.execute(simulation.insert(), [{"id": 1, **asdict(stored)}])


def initialise(
    engine: Engine,
    *,
    seed: int,
    anchor_date: date | None,
    clock: Clock = utc_now,
) -> Initialisation:
    """Generates and stores the dataset unless one is stored already.

    `anchor_date` is `DEMOBANK_ANCHOR_DATE`: when it is `None`, the anchor
    date is today's date in UTC from `clock`. An anchor date after today is
    rejected. Raises `DatabaseStartupError` with one line when the database
    cannot be reached, the stored schema version differs, or the anchor date
    is after today. Nothing is changed in any of these cases.
    """
    connection = _connect(engine)
    with connection, connection.begin():
        # Taken first, so a second process waits here until the first one has
        # committed, then finds its `simulation` row.
        connection.execute(select(func.pg_advisory_xact_lock(ADVISORY_LOCK_KEY)))
        connection.execute(CreateSchema(SCHEMA, if_not_exists=True))
        stored = _stored_simulation(connection)
        if stored is not None:
            _warn_about_ignored_settings(stored, seed, anchor_date)
            count = connection.execute(select(func.count()).select_from(transactions))
            initialisation = Initialisation(
                simulation=stored, generated=False, transaction_count=count.scalar_one()
            )
            logger.info(
                "DemoBank keeps the stored dataset: seed %s, anchor date %s, %s transactions",
                stored.seed,
                stored.anchor_date.isoformat(),
                initialisation.transaction_count,
            )
            return initialisation

        now = clock().astimezone(UTC)
        today = now.date()
        anchor = anchor_date if anchor_date is not None else today
        if anchor > today:
            raise DatabaseStartupError(ANCHOR_AFTER_TODAY)
        metadata.create_all(connection)
        dataset = generate(seed, anchor)
        _insert_dataset(connection, dataset)
        stored = StoredSimulation(
            seed=seed, anchor_date=anchor, schema_version=SCHEMA_VERSION, generated_at=now
        )
        _insert_simulation(connection, stored)
    logger.info(
        "DemoBank generated its history: seed %s, anchor date %s, %s transactions",
        seed,
        anchor.isoformat(),
        len(dataset.transactions),
    )
    return Initialisation(
        simulation=stored, generated=True, transaction_count=len(dataset.transactions)
    )


def _first_line(error: SQLAlchemyError, password: str | None) -> str:
    source: Any = error.orig if isinstance(error, DBAPIError) and error.orig else error
    line = (str(source).strip().splitlines() or [type(error).__name__])[0]
    return line.replace(password, "***") if password else line


def prepare_database(settings: Settings, *, clock: Clock = utc_now) -> Initialisation:
    """The database step of the app's startup, from the settings.

    Every database error becomes a `DatabaseStartupError` with one line that
    holds neither the URL nor its password.
    """
    url = database_url(settings.demobank_database_url.get_secret_value())
    engine = make_engine(url)
    message = None
    try:
        return initialise(
            engine,
            seed=settings.demobank_seed,
            anchor_date=settings.demobank_anchor_date,
            clock=clock,
        )
    except SQLAlchemyError as exc:
        reason = _first_line(exc, url.password)
        message = f"DemoBank cannot prepare the demobank_sim schema: {reason}"
    finally:
        engine.dispose()
    # Outside the `except` block: the driver error is not chained.
    raise DatabaseStartupError(message)
