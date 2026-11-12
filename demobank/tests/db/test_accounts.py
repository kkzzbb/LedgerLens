"""`GET /v1/accounts` and `GET /v1/accounts/{account_id}/balance` on PostgreSQL (#10)."""

import re
from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.engine import URL

from demobank.api.v1 import get_engine
from demobank.app import create_app
from demobank.config import Settings, get_settings
from demobank.db.startup import initialise
from demobank.db.tables import transactions
from demobank.generator import generate

pytestmark = pytest.mark.db

API_KEY = "test-api-key"
HEADERS = {"X-API-Key": API_KEY}
ACCOUNT_ID = "acc_operating_001"
SEED = 42
ANCHOR = date(2026, 6, 30)
BALANCE_URL = f"/v1/accounts/{ACCOUNT_ID}/balance"
UNKNOWN_URL = "/v1/accounts/acc_unknown/balance"


def no_database(settings: Settings) -> None:
    """The dataset is stored by the fixture, not by the startup."""


@pytest.fixture
def client(
    monkeypatch: pytest.MonkeyPatch, empty_database_url: URL, engine: Engine
) -> Iterator[TestClient]:
    """A started app whose routes read the test database, holding seed 42 at 2026-06-30."""
    monkeypatch.setenv("DEMOBANK_API_KEY", API_KEY)
    monkeypatch.setenv(
        "DEMOBANK_DATABASE_URL", empty_database_url.render_as_string(hide_password=False)
    )
    get_settings.cache_clear()
    initialise(
        engine, seed=SEED, anchor_date=ANCHOR, clock=lambda: datetime(2026, 7, 1, tzinfo=UTC)
    )
    app = create_app(database_step=no_database)
    app.dependency_overrides[get_engine] = lambda: engine
    with TestClient(app) as started:
        yield started
    get_settings.cache_clear()


def expected_balance() -> Decimal:
    dataset = generate(SEED, ANCHOR)
    total = dataset.account.opening_balance
    for t in dataset.transactions:
        total += t.amount if t.direction == "credit" else -t.amount
    return total


def test_accounts_lists_the_generated_account(client: TestClient) -> None:
    response = client.get("/v1/accounts", headers=HEADERS)
    assert response.status_code == 200
    assert response.json() == [
        {
            "account_id": ACCOUNT_ID,
            "display_name": "Demo Retail Ltd — Operating",
            "currency": "EUR",
        }
    ]


def test_balance_matches_an_independent_decimal_sum(client: TestClient) -> None:
    before = datetime.now(UTC).replace(microsecond=0)
    response = client.get(BALANCE_URL, headers=HEADERS)
    after = datetime.now(UTC)
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"account_id", "balance", "currency", "as_of"}
    assert body["account_id"] == ACCOUNT_ID
    assert body["currency"] == "EUR"
    assert isinstance(body["balance"], str)
    assert re.fullmatch(r"-?\d+\.\d{2}", body["balance"])
    assert Decimal(body["balance"]) == expected_balance()
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", body["as_of"])
    as_of = datetime.strptime(body["as_of"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    assert before <= as_of <= after


def test_balance_includes_the_planted_anomalies(client: TestClient) -> None:
    dataset = generate(SEED, ANCHOR)
    history = dataset.account.opening_balance
    for t in dataset.transactions[:-3]:
        history += t.amount if t.direction == "credit" else -t.amount

    response = client.get(BALANCE_URL, headers=HEADERS)

    assert Decimal(response.json()["balance"]) == history - Decimal("8760.00")


def test_balance_drops_by_an_appended_debit(client: TestClient, engine: Engine) -> None:
    before = Decimal(client.get(BALANCE_URL, headers=HEADERS).json()["balance"])
    amount = Decimal("123.45")
    with engine.begin() as connection:
        connection.execute(
            transactions.insert(),
            [
                {
                    "transaction_id": "tx_test_extra_debit",
                    "account_id": ACCOUNT_ID,
                    "booking_date": ANCHOR,
                    "value_date": ANCHOR,
                    "amount": amount,
                    "currency": "EUR",
                    "direction": "debit",
                    "counterparty_name": "Test Counterparty",
                    "status": "booked",
                }
            ],
        )
    after = Decimal(client.get(BALANCE_URL, headers=HEADERS).json()["balance"])
    assert before - after == amount


def test_unknown_account_is_404(client: TestClient) -> None:
    response = client.get(UNKNOWN_URL, headers=HEADERS)
    assert response.status_code == 404
    assert response.json() == {"error": "account_not_found"}


@pytest.mark.parametrize("path", ["/v1/accounts", BALANCE_URL, UNKNOWN_URL])
@pytest.mark.parametrize("headers", [{}, {"X-API-Key": "wrong-key"}])
def test_routes_need_the_api_key(client: TestClient, path: str, headers: dict[str, str]) -> None:
    response = client.get(path, headers=headers)
    assert response.status_code == 401
    assert response.json() == {"error": "unauthorized"}
