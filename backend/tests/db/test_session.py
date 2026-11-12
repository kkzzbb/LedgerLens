"""Unit tests for `ledgerlens.db.session` and `ledgerlens.db.base`: no database needed."""

import os
import subprocess
import sys
from collections.abc import Iterator
from typing import Any

import pytest
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, event
from sqlalchemy.engine import make_url

from ledgerlens.config import get_settings
from ledgerlens.db import session as db_session_module
from ledgerlens.db.base import NAMING_CONVENTION, SCHEMA, Base
from ledgerlens.db.session import (
    database_url,
    get_engine,
    get_sessionmaker,
    make_engine,
)
from tests.db.support import BACKEND_DIR, alembic_config

MARKER_PASSWORD = "MARKER-db-password"


@pytest.fixture
def clean_caches() -> Iterator[None]:
    def clear() -> None:
        get_settings.cache_clear()
        get_engine.cache_clear()
        db_session_module._sessionmaker.cache_clear()

    clear()
    yield
    clear()


def test_import_reads_no_settings_and_opens_no_connection() -> None:
    environment = {
        key: value
        for key, value in os.environ.items()
        if key not in {"DATABASE_URL", "DEMOBANK_API_KEY"}
    }
    code = (
        "import ledgerlens.db.session as s\n"
        "from ledgerlens.config import get_settings\n"
        "assert get_settings.cache_info().currsize == 0\n"
        "assert s.get_engine.cache_info().currsize == 0\n"
        "print('ok')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=BACKEND_DIR,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://user:pw@localhost:5432/ledgerlens",
        "postgres://user:pw@localhost:5432/ledgerlens",
        "postgresql+psycopg://user:pw@localhost:5432/ledgerlens",
    ],
)
def test_postgres_schemes_use_the_psycopg_driver(url: str) -> None:
    parsed = database_url(url)
    assert parsed.drivername == "postgresql+psycopg"
    assert parsed.username == "user"
    assert parsed.password == "pw"
    assert parsed.host == "localhost"
    assert parsed.port == 5432
    assert parsed.database == "ledgerlens"


@pytest.mark.parametrize(
    "url",
    [
        f"sqlite://user:{MARKER_PASSWORD}@localhost/ledgerlens",
        f"postgresql+psycopg2://user:{MARKER_PASSWORD}@localhost:5432/ledgerlens",
        f"mysql://user:{MARKER_PASSWORD}@localhost/ledgerlens",
        f"user:{MARKER_PASSWORD}@localhost:5432/ledgerlens",
    ],
)
def test_other_schemes_raise_without_the_url(url: str) -> None:
    with pytest.raises(ValueError) as caught:
        database_url(url)
    message = str(caught.value)
    assert "scheme" in message
    assert MARKER_PASSWORD not in message
    assert "localhost" not in message
    assert caught.value.__cause__ is None


def test_make_engine_rejects_other_schemes_without_the_url() -> None:
    with pytest.raises(ValueError) as caught:
        make_engine(f"sqlite://user:{MARKER_PASSWORD}@localhost/x")
    assert MARKER_PASSWORD not in str(caught.value)


def test_unparsable_url_raises_without_the_url() -> None:
    with pytest.raises(ValueError) as caught:
        database_url(f"postgresql://user:{MARKER_PASSWORD}@localhost:notaport/x")
    assert MARKER_PASSWORD not in str(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None or caught.value.__suppress_context__


def test_make_engine_is_synchronous_with_pre_ping_and_no_echo() -> None:
    engine = make_engine("postgresql://user:pw@localhost:5432/ledgerlens")
    try:
        assert engine.url.drivername == "postgresql+psycopg"
        assert engine.echo is False
        assert engine.pool._pre_ping is True
    finally:
        engine.dispose()


class _Captured(Exception):
    pass


def _driver_connect_arguments(engine: Engine) -> dict[str, Any]:
    """The keyword arguments the engine hands to the driver's `connect()`.

    The connection attempt is stopped before it reaches the driver.
    """
    captured: dict[str, Any] = {}

    @event.listens_for(engine, "do_connect")
    def capture(dialect: Any, record: Any, cargs: Any, cparams: dict[str, Any]) -> None:
        captured.update(cparams)
        raise _Captured

    with pytest.raises(_Captured), engine.connect():
        pass
    return captured


def test_make_engine_passes_a_5_second_connect_timeout_by_default() -> None:
    engine = make_engine("postgresql://user:pw@localhost:5432/ledgerlens")
    try:
        assert _driver_connect_arguments(engine)["connect_timeout"] == 5
    finally:
        engine.dispose()


def test_make_engine_passes_the_given_connect_timeout() -> None:
    url = make_url("postgresql://user:pw@localhost:5432/ledgerlens")
    engine = make_engine(url, connect_timeout=2)
    try:
        assert _driver_connect_arguments(engine)["connect_timeout"] == 2
    finally:
        engine.dispose()


def test_get_engine_is_built_once_from_database_url(
    monkeypatch: pytest.MonkeyPatch, clean_caches: None
) -> None:
    monkeypatch.setenv("DATABASE_URL", f"postgres://user:{MARKER_PASSWORD}@dbhost:5432/app")
    monkeypatch.setenv("DEMOBANK_API_KEY", "test-api-key")
    engine = get_engine()
    assert get_engine() is engine
    assert engine.url.drivername == "postgresql+psycopg"
    assert engine.url.host == "dbhost"
    assert engine.url.database == "app"
    assert MARKER_PASSWORD not in repr(engine)
    engine.dispose()


def test_get_sessionmaker_is_bound_to_the_engine(
    monkeypatch: pytest.MonkeyPatch, clean_caches: None
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pw@dbhost:5432/app")
    monkeypatch.setenv("DEMOBANK_API_KEY", "test-api-key")
    maker = get_sessionmaker()
    assert maker.kw["bind"] is get_engine()
    assert maker.kw["expire_on_commit"] is False
    get_engine().dispose()


def test_base_metadata_uses_the_ledgerlens_schema_and_naming_convention() -> None:
    assert SCHEMA == "ledgerlens"
    assert Base.metadata.schema == "ledgerlens"
    for key in ("ix", "uq", "ck", "fk", "pk"):
        assert Base.metadata.naming_convention[key] == NAMING_CONVENTION[key]


def test_alembic_without_database_url_exits_with_one_line() -> None:
    environment = {
        key: value
        for key, value in os.environ.items()
        if key not in {"DATABASE_URL", "DEMOBANK_API_KEY"}
    }
    environment["DATABASE_URL"] = "   "
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_DIR,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert result.stderr.strip() == "DATABASE_URL is required but not set"
    assert "Traceback" not in result.stdout + result.stderr


def test_migrations_form_one_chain_from_0001() -> None:
    script = ScriptDirectory.from_config(alembic_config(make_url("postgresql://unused/unused")))
    revisions = list(script.walk_revisions())
    assert len(script.get_heads()) == 1
    assert revisions[-1].revision == "0001"
    assert revisions[-1].down_revision is None
