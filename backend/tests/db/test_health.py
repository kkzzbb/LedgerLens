"""The health check against a real PostgreSQL database."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import URL

from ledgerlens.api.app import create_app
from ledgerlens.api.health import get_database_check
from ledgerlens.db.session import make_engine
from ledgerlens.services.health import database_is_reachable, select_one

pytestmark = pytest.mark.db


def test_real_check_is_ok(empty_database_url: URL) -> None:
    engine = make_engine(empty_database_url)
    try:
        assert database_is_reachable(engine) is True
    finally:
        engine.dispose()


def test_health_endpoint_is_ok_on_a_real_database(empty_database_url: URL) -> None:
    engine = make_engine(empty_database_url)
    app = create_app()
    app.dependency_overrides[get_database_check] = lambda: lambda: select_one(engine)
    try:
        response = TestClient(app).get("/api/health")
    finally:
        engine.dispose()
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}
