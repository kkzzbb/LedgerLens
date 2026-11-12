"""Unit tests for the application: `/health`, the `/v1` API key check, OpenAPI.

The app is called through FastAPI's `TestClient`, with the settings set
through the environment. The database step of the startup is replaced by a
no-op (`create_app(database_step=...)`): no database and no Docker.
"""

import logging
import os
import re
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.routing import RouteContext, iter_route_contexts
from fastapi.testclient import TestClient

from demobank.api import auth, v1
from demobank.app import StartupError, create_app
from demobank.config import Settings, get_settings
from demobank.db.startup import CANNOT_CONNECT, DatabaseStartupError

DEMOBANK_DIR = Path(__file__).resolve().parents[2]
SETTINGS_VARIABLES = {
    "DEMOBANK_API_KEY",
    "DEMOBANK_ADMIN_ENABLED",
    "DEMOBANK_ADMIN_KEY",
    "DEMOBANK_DATABASE_URL",
    "DEMOBANK_SEED",
    "DEMOBANK_ANCHOR_DATE",
}
DATABASE_URL = "postgresql://ledgerlens:ledgerlens@db:5432/ledgerlens"
PASSWORD_MARKER = "MARKERdbpw9"
# Port 1 on the loopback interface is closed: connecting fails at once.
UNREACHABLE_URL = f"postgresql://ledgerlens:{PASSWORD_MARKER}@127.0.0.1:1/ledgerlens"

API_KEY = "test-api-key"
ADMIN_KEY = "test-admin-key"
API_KEY_MARKER = "MARKERapikey42"
OK = {"status": "ok"}
UNAUTHORIZED = {"error": "unauthorized"}


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Only a valid DEMOBANK_DATABASE_URL is set, and nothing is cached."""
    for name in SETTINGS_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DEMOBANK_DATABASE_URL", DATABASE_URL)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def no_database(settings: Settings) -> None:
    """Replaces the database step of the startup."""


def app_without_database() -> FastAPI:
    return create_app(database_step=no_database)


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """A started app (its lifespan has run) with admin enabled and a distinct admin key."""
    monkeypatch.setenv("DEMOBANK_API_KEY", API_KEY)
    monkeypatch.setenv("DEMOBANK_ADMIN_ENABLED", "true")
    monkeypatch.setenv("DEMOBANK_ADMIN_KEY", ADMIN_KEY)
    with TestClient(app_without_database()) as started:
        yield started


def environment_without_settings() -> dict[str, str]:
    return {key: value for key, value in os.environ.items() if key not in SETTINGS_VARIABLES}


# Application factory and startup


def test_app_title() -> None:
    assert create_app().title == "DemoBank"


def test_create_app_reads_no_settings() -> None:
    code = (
        "from demobank.app import create_app\n"
        "from demobank.config import get_settings\n"
        "app = create_app()\n"
        "assert get_settings.cache_info().currsize == 0\n"
        "assert get_settings.cache_info().misses == 0\n"
        "print('ok')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=DEMOBANK_DIR,
        env=environment_without_settings(),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_startup_fails_without_api_key() -> None:
    # The default database step is not reached: the settings are checked first.
    with pytest.raises(StartupError) as caught, TestClient(create_app()):
        pass
    assert "DEMOBANK_API_KEY is required but not set" in str(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_uvicorn_exits_non_zero_without_api_key() -> None:
    environment = environment_without_settings()
    environment["DEMOBANK_ADMIN_KEY"] = "MARKER-demobank-admin-key"
    result = subprocess.run(
        [sys.executable, "-m", "uvicorn", "--factory", "demobank.app:create_app", "--port", "0"],
        cwd=DEMOBANK_DIR,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "DEMOBANK_API_KEY" in output
    assert "MARKER" not in output


def test_database_step_runs_after_the_settings_check(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEMOBANK_API_KEY", API_KEY)
    monkeypatch.setenv("DEMOBANK_SEED", "7")
    calls: list[Settings] = []

    with TestClient(create_app(database_step=calls.append)) as client:
        assert client.get("/health").status_code == 200

    assert [settings.demobank_seed for settings in calls] == [7]


def test_database_step_is_skipped_when_the_settings_are_invalid() -> None:
    calls: list[Settings] = []

    with pytest.raises(StartupError), TestClient(create_app(database_step=calls.append)):
        pass

    assert calls == []


def test_database_step_failure_stops_the_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEMOBANK_API_KEY", API_KEY)

    def failing(settings: Settings) -> None:
        raise DatabaseStartupError("DemoBank test failure")

    with pytest.raises(StartupError) as caught, TestClient(create_app(database_step=failing)):
        pass

    assert str(caught.value) == "DemoBank test failure"
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_unreachable_database_stops_the_startup_with_one_line(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    monkeypatch.setenv("DEMOBANK_API_KEY", API_KEY)
    monkeypatch.setenv("DEMOBANK_DATABASE_URL", UNREACHABLE_URL)

    started = time.monotonic()
    with pytest.raises(StartupError) as caught, TestClient(create_app()):
        pass

    assert time.monotonic() - started < 5
    assert str(caught.value) == CANNOT_CONNECT
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert PASSWORD_MARKER not in caplog.text
    assert "127.0.0.1:1" not in caplog.text


def test_uvicorn_exits_non_zero_without_a_database() -> None:
    environment = environment_without_settings()
    environment["DEMOBANK_API_KEY"] = API_KEY
    environment["DEMOBANK_DATABASE_URL"] = UNREACHABLE_URL
    result = subprocess.run(
        [sys.executable, "-m", "uvicorn", "--factory", "demobank.app:create_app", "--port", "0"],
        cwd=DEMOBANK_DIR,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    output = result.stdout + result.stderr

    assert result.returncode != 0
    assert CANNOT_CONNECT in output
    assert PASSWORD_MARKER not in output
    assert UNREACHABLE_URL not in output
    assert "ledgerlens@" not in output


# /health


@pytest.mark.parametrize(
    "headers",
    [{}, {"X-API-Key": "wrong"}, {"X-API-Key": API_KEY}],
    ids=["missing", "wrong", "correct"],
)
def test_health_is_200_with_or_without_a_key(client: TestClient, headers: dict[str, str]) -> None:
    response = client.get("/health", headers=headers)

    assert response.status_code == 200
    assert response.json() == OK


def test_health_needs_no_settings_and_no_database() -> None:
    # Called without the lifespan: no settings are read for /health.
    response = TestClient(create_app()).get("/health")

    assert response.status_code == 200
    assert response.json() == OK
    assert get_settings.cache_info().misses == 0


# /v1/ping and the API key


def test_ping_with_the_correct_key(client: TestClient) -> None:
    response = client.get("/v1/ping", headers={"X-API-Key": API_KEY})

    assert response.status_code == 200
    assert response.json() == OK


@pytest.mark.parametrize("name", ["x-api-key", "X-API-KEY", "x-Api-kEy"])
def test_header_name_is_case_insensitive(client: TestClient, name: str) -> None:
    response = client.get("/v1/ping", headers={name: API_KEY})

    assert response.status_code == 200
    assert response.json() == OK


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"X-API-Key": ""},
        {"X-API-Key": "wrong-key"},
        {"X-API-Key": f" {API_KEY}"},
        {"X-API-Key": f"{API_KEY} "},
        {"X-API-Key": "test-api-kéy".encode()},
        {"X-API-Key": b"\xff\xfe\x00test"},
        {"X-API-Key": ADMIN_KEY},
        {"Authorization": f"Bearer {API_KEY}"},
    ],
    ids=[
        "missing",
        "empty",
        "wrong",
        "leading-space",
        "trailing-space",
        "non-ascii-utf8",
        "non-ascii-bytes",
        "admin-key",
        "other-header",
    ],
)
def test_ping_without_the_correct_key_is_401(
    client: TestClient, headers: dict[str, str | bytes]
) -> None:
    response = client.get("/v1/ping", headers=headers)

    assert response.status_code == 401
    assert response.json() == UNAUTHORIZED
    assert response.content == b'{"error":"unauthorized"}'


def test_non_ascii_api_key_matches_its_utf8_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    # Starlette hands header values over decoded as Latin-1 (one character per
    # byte). The TestClient re-encodes every header as UTF-8, so the raw-byte
    # cases are checked on the dependency itself.
    key = "cl\u00e9-secr\u00e8te"
    monkeypatch.setenv("DEMOBANK_API_KEY", key)
    as_utf8 = key.encode("utf-8").decode("latin-1")
    as_latin1 = key.encode("latin-1").decode("latin-1")

    auth.require_api_key(as_utf8)
    with pytest.raises(auth.UnauthorizedError):
        auth.require_api_key(as_latin1)
    with pytest.raises(auth.UnauthorizedError):
        auth.require_api_key(None)
    with TestClient(app_without_database()) as client:
        response = client.get("/v1/ping", headers={"X-API-Key": key.encode("utf-8")})
    assert response.status_code == 200


def test_unknown_v1_path_is_404(client: TestClient) -> None:
    response = client.get("/v1/nope", headers={"X-API-Key": API_KEY})

    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}


def v1_routes(app: FastAPI) -> list[RouteContext]:
    """Every route of `app.routes` under `/v1`, with included routers expanded.

    FastAPI 0.162 keeps an included router as one entry of `app.routes`;
    `iter_route_contexts` yields the routes inside it with their full path.
    """
    return [
        context
        for context in iter_route_contexts(app.routes)
        if (context.path or "").startswith("/v1")
    ]


def test_v1_router_carries_one_shared_key_dependency() -> None:
    assert [d.dependency for d in v1.router.dependencies] == [auth.require_api_key]
    routes = v1_routes(create_app())
    assert routes, "no /v1 route is registered"
    for context in routes:
        # The router's dependency applies to each route exactly once: no
        # route adds a copy of its own.
        checks = [d.dependency for d in context.dependencies]
        assert checks == [auth.require_api_key], context.path


def test_every_v1_route_rejects_a_request_without_a_key(client: TestClient) -> None:
    app = client.app
    assert isinstance(app, FastAPI)
    routes = v1_routes(app)
    assert routes, "no /v1 route is registered"

    for context in routes:
        path = re.sub(r"\{[^}]+\}", "dummy", context.path or "")
        for method in sorted(context.methods or ()):
            response = client.request(method, path)
            assert response.status_code == 401, f"{method} {context.path}"
            assert response.json() == UNAUTHORIZED, f"{method} {context.path}"


def test_the_key_is_compared_in_constant_time_on_bytes() -> None:
    source = Path(auth.__file__).read_text()

    assert "compare_digest(" in source
    assert '.encode("utf-8")' in source


def test_the_key_never_appears_in_responses_or_logs(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    monkeypatch.setenv("DEMOBANK_API_KEY", API_KEY_MARKER)
    with TestClient(app_without_database()) as client:
        responses = [
            client.get("/v1/ping"),
            client.get("/v1/ping", headers={"X-API-Key": "wrong"}),
            client.get("/v1/ping", headers={"X-API-Key": API_KEY_MARKER}),
            client.get("/health", headers={"X-API-Key": API_KEY_MARKER}),
        ]

    assert [r.status_code for r in responses] == [401, 401, 200, 200]
    for response in responses:
        assert API_KEY_MARKER not in response.text
        assert API_KEY_MARKER not in repr(response.headers.raw)
    assert API_KEY_MARKER not in caplog.text
    for record in caplog.records:
        assert API_KEY_MARKER not in record.getMessage()
        assert API_KEY_MARKER not in repr(record.args)


def test_the_401_path_writes_no_log_line(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    caplog.clear()

    client.get("/v1/ping")
    client.get("/v1/ping", headers={"X-API-Key": "wrong"})

    # httpx logs each request on the client side; that is not the service.
    assert [r for r in caplog.records if not r.name.startswith("httpx")] == []


# /docs and /openapi.json


def test_docs_and_openapi_are_public(client: TestClient) -> None:
    assert client.get("/docs").status_code == 200
    assert client.get("/openapi.json").status_code == 200


def test_openapi_declares_the_api_key_scheme_on_v1_only(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()

    schemes = spec["components"]["securitySchemes"]
    assert len(schemes) == 1
    [(scheme_name, scheme)] = schemes.items()
    assert scheme["type"] == "apiKey"
    assert scheme["in"] == "header"
    assert scheme["name"] == "X-API-Key"
    assert spec["paths"]["/v1/ping"]["get"]["security"] == [{scheme_name: []}]
    assert "security" not in spec["paths"]["/health"]["get"]
    assert "security" not in spec
