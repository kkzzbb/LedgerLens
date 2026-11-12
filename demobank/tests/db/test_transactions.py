"""`GET /v1/accounts/{account_id}/transactions` on PostgreSQL (#11)."""

import base64
import re
from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.engine import URL

from demobank.api.v1 import get_engine
from demobank.app import create_app
from demobank.config import get_settings
from demobank.db.startup import initialise
from demobank.db.tables import transactions
from demobank.generator import generate
from tests.db.test_accounts import ACCOUNT_ID, ANCHOR, API_KEY, HEADERS, SEED, no_database

pytestmark = pytest.mark.db

URL_PATH = f"/v1/accounts/{ACCOUNT_ID}/transactions"
FIELDS = {
    "transaction_id",
    "account_id",
    "booking_date",
    "value_date",
    "amount",
    "currency",
    "direction",
    "counterparty_name",
    "counterparty_reference",
    "description",
    "status",
}


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


def get_page(client: TestClient, **params: Any) -> dict[str, Any]:
    response = client.get(URL_PATH, headers=HEADERS, params=params)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    assert set(body) == {"transactions", "next_cursor", "has_more"}
    return body


def page_through(client: TestClient, limit: int, cursor: str | None = None) -> list[dict[str, Any]]:
    """Every page until `has_more` is false; returns the pages."""
    pages = []
    while True:
        params: dict[str, Any] = {"limit": limit}
        if cursor is not None:
            params["cursor"] = cursor
        page = get_page(client, **params)
        pages.append(page)
        cursor = page["next_cursor"]
        if not page["has_more"]:
            return pages


def test_paging_with_limit_7_returns_every_record_once_in_order(client: TestClient) -> None:
    expected = sorted(
        generate(SEED, ANCHOR).transactions, key=lambda t: (t.booking_date, t.transaction_id)
    )
    pages = page_through(client, 7)
    records = [t for page in pages for t in page["transactions"]]
    assert [r["transaction_id"] for r in records] == [t.transaction_id for t in expected]
    assert all(len(page["transactions"]) == 7 for page in pages[:-1])
    assert pages[-1]["has_more"] is False
    for record, stored in zip(records, expected, strict=True):
        assert set(record) == FIELDS
        assert re.fullmatch(r"\d+\.\d{2}", record["amount"])
        assert Decimal(record["amount"]) == stored.amount
        assert record["booking_date"] == stored.booking_date.isoformat()
        assert record["value_date"] == stored.value_date.isoformat()
        assert record["direction"] == stored.direction
        assert record["account_id"] == ACCOUNT_ID
        assert record["counterparty_reference"] == stored.counterparty_reference
        assert record["description"] == stored.description
    last = records[-1]
    decoded = base64.urlsafe_b64decode(pages[-1]["next_cursor"]).decode()
    assert decoded == f'{{"b":"{last["booking_date"]}","t":"{last["transaction_id"]}"}}'


def test_final_cursor_returns_an_empty_page_with_the_same_cursor(client: TestClient) -> None:
    final = page_through(client, 500)[-1]["next_cursor"]
    again = get_page(client, cursor=final)
    assert again == {"transactions": [], "next_cursor": final, "has_more": False}


def test_a_row_inserted_between_calls_appears_in_a_later_page(
    client: TestClient, engine: Engine
) -> None:
    first = get_page(client, limit=7)
    seen = [t["transaction_id"] for t in first["transactions"]]
    with engine.begin() as connection:
        connection.execute(
            transactions.insert(),
            [
                {
                    "transaction_id": "txn_999999",
                    "account_id": ACCOUNT_ID,
                    "booking_date": date(2026, 7, 1),
                    "value_date": date(2026, 7, 1),
                    "amount": Decimal("10.00"),
                    "currency": "EUR",
                    "direction": "credit",
                    "counterparty_name": "Test Counterparty",
                    "status": "booked",
                }
            ],
        )
    rest = page_through(client, 7, first["next_cursor"])
    seen += [t["transaction_id"] for page in rest for t in page["transactions"]]
    assert seen[-1] == "txn_999999"
    assert len(seen) == len(set(seen)) == len(generate(SEED, ANCHOR).transactions) + 1


def test_limit_defaults_to_100(client: TestClient) -> None:
    body = get_page(client)
    assert len(body["transactions"]) == 100
    assert body["has_more"] is True


@pytest.mark.parametrize("limit", [1, 500])
def test_limit_bounds_are_accepted(client: TestClient, limit: int) -> None:
    body = get_page(client, limit=limit)
    assert len(body["transactions"]) == min(limit, len(generate(SEED, ANCHOR).transactions))


@pytest.mark.parametrize("limit", [0, 501])
def test_limit_out_of_bounds_is_422(client: TestClient, limit: int) -> None:
    response = client.get(URL_PATH, headers=HEADERS, params={"limit": limit})
    assert response.status_code == 422


@pytest.mark.parametrize(
    "cursor",
    [
        "%%%not-base64%%%",
        base64.urlsafe_b64encode(b'{"x": 1}').decode(),
        base64.urlsafe_b64encode(b'{"b": "2026-13-01", "t": "txn_000001"}').decode(),
    ],
)
def test_invalid_cursor_is_400(client: TestClient, cursor: str) -> None:
    response = client.get(URL_PATH, headers=HEADERS, params={"cursor": cursor})
    assert response.status_code == 400
    assert response.json() == {"error": "invalid_cursor"}


def test_unknown_account_is_404(client: TestClient) -> None:
    response = client.get("/v1/accounts/acc_unknown/transactions", headers=HEADERS)
    assert response.status_code == 404
    assert response.json() == {"error": "account_not_found"}


def test_route_needs_the_api_key(client: TestClient) -> None:
    response = client.get(URL_PATH, headers={"X-API-Key": "wrong-key"})
    assert response.status_code == 401
