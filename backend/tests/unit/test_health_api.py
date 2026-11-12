"""Unit tests for `GET /api/health` and the application factory: no database.

The route is called through FastAPI's `TestClient`, with the database check
replaced through `app.dependency_overrides`.
"""

import logging
import os
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ledgerlens.api.app import StartupError, create_app
from ledgerlens.api.health import get_database_check
from ledgerlens.config import get_settings
from ledgerlens.db import session as db_session_module
from ledgerlens.db.session import get_engine, make_engine
from ledgerlens.services.health import DatabaseCheck, select_one

BACKEND_DIR = Path(__file__).resolve().parents[2]
MARKER_PASSWORD = "MARKERapipw42"
HEALTHY = {"status": "ok", "database": "ok"}
DEGRADED = {"status": "degraded", "database": "unavailable"}


@pytest.fixture(autouse=True)
def clean_caches(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DEMOBANK_API_KEY", raising=False)

    def clear() -> None:
        get_settings.cache_clear()
        get_engine.cache_clear()
        db_session_module._sessionmaker.cache_clear()

    clear()
    yield
    clear()


def app_with_check(check: DatabaseCheck) -> FastAPI:
    app = create_app()
    app.dependency_overrides[get_database_check] = lambda: check
    return app


def environment_without_settings() -> dict[str, str]:
    return {
        key: value
        for key, value in os.environ.items()
        if key not in {"DATABASE_URL", "DEMOBANK_API_KEY"}
    }


def test_healthy_database_gives_200() -> None:
    response = TestClient(app_with_check(lambda: True)).get("/api/health")
    assert response.status_code == 200
    assert response.json() == HEALTHY


def test_check_returning_false_gives_503() -> None:
    response = TestClient(app_with_check(lambda: False)).get("/api/health")
    assert response.status_code == 503
    assert response.json() == DEGRADED


def test_check_raising_gives_503() -> None:
    def check() -> bool:
        raise RuntimeError("boom")

    response = TestClient(app_with_check(check)).get("/api/health")
    assert response.status_code == 503
    assert response.json() == DEGRADED


def test_check_sleeping_10_seconds_gives_503_in_under_3_seconds() -> None:
    release = threading.Event()

    def check() -> bool:
        release.wait(10)  # sleeps 10 s unless the test ends first
        return True

    client = TestClient(app_with_check(check))
    started = time.monotonic()
    try:
        response = client.get("/api/health")
        elapsed = time.monotonic() - started
    finally:
        release.set()
    assert response.status_code == 503
    assert response.json() == DEGRADED
    assert elapsed < 3


def test_no_authentication_header_is_needed() -> None:
    client = TestClient(app_with_check(lambda: True))
    response = client.get("/api/health", headers={})
    assert "authorization" not in {name.lower() for name in client.headers}
    assert response.status_code == 200


def test_real_check_on_a_refused_port_leaks_neither_url_nor_password(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger="ledgerlens")
    engine = make_engine(f"postgresql://ledgerlens:{MARKER_PASSWORD}@127.0.0.1:1/ledgerlens")
    try:
        response = TestClient(app_with_check(lambda: select_one(engine))).get("/api/health")
    finally:
        engine.dispose()
    assert response.status_code == 503
    assert response.json() == DEGRADED
    for text in (response.text, caplog.text):
        assert MARKER_PASSWORD not in text
        assert "127.0.0.1" not in text
        assert "postgresql" not in text
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert [r.getMessage() for r in warnings] == ["Database health check failed: OperationalError"]


def test_default_check_uses_the_application_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", f"postgresql://u:{MARKER_PASSWORD}@127.0.0.1:1/app")
    monkeypatch.setenv("DEMOBANK_API_KEY", "test-api-key")
    with TestClient(create_app()) as client:
        response = client.get("/api/health")
    assert response.status_code == 503
    assert response.json() == DEGRADED
    assert get_engine.cache_info().currsize == 1
    get_engine().dispose()


def test_create_app_reads_no_settings_and_opens_no_connection() -> None:
    code = (
        "from ledgerlens.api.app import create_app\n"
        "from ledgerlens.config import get_settings\n"
        "from ledgerlens.db.session import get_engine\n"
        "app = create_app()\n"
        "assert get_settings.cache_info().currsize == 0\n"
        "assert get_engine.cache_info().currsize == 0\n"
        "print('ok')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=BACKEND_DIR,
        env=environment_without_settings(),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_startup_fails_without_database_url() -> None:
    with pytest.raises(StartupError) as caught, TestClient(create_app()):
        pass
    assert "DATABASE_URL is required but not set" in str(caught.value)


def test_startup_succeeds_with_the_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:pw@127.0.0.1:1/app")
    monkeypatch.setenv("DEMOBANK_API_KEY", "test-api-key")
    with TestClient(app_with_check(lambda: True)) as client:
        assert client.get("/api/health").status_code == 200


def test_uvicorn_exits_non_zero_without_database_url() -> None:
    environment = environment_without_settings()
    environment["DEMOBANK_API_KEY"] = "MARKER-demobank-key"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "--factory",
            "ledgerlens.api.app:create_app",
            "--port",
            "0",
        ],
        cwd=BACKEND_DIR,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "DATABASE_URL is required but not set" in output
    assert "MARKER-demobank-key" not in output
