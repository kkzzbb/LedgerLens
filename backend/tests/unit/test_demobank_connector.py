"""The DemoBank connector (#17), against `httpx.MockTransport`."""

from collections.abc import Callable
from typing import Any

import httpx
import pytest

from ledgerlens.config import Settings
from ledgerlens.connectors.base import BankConnector, ConnectorError, TransactionPage
from ledgerlens.connectors.demobank import DemoBankConnector

BASE_URL = "http://demobank.test"
API_KEY = "secret-key-MARKER-1234"
BODY_MARKER = "BODY-MARKER-5678"

Handler = Callable[[httpx.Request], httpx.Response]

TRANSACTION: dict[str, Any] = {
    "transaction_id": "t-1",
    "account_id": "acc-1",
    "booking_date": "2026-01-02",
    "value_date": "2026-01-02",
    "amount": "1234.50",
    "currency": "EUR",
    "direction": "debit",
    "counterparty_name": "Acme",
    "counterparty_reference": None,
    "description": None,
    "status": "booked",
}


def connector(handler: Handler) -> DemoBankConnector:
    return DemoBankConnector(BASE_URL, API_KEY, transport=httpx.MockTransport(handler))


def recording(response: httpx.Response, sent: list[httpx.Request]) -> Handler:
    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return response

    return handler


def test_demobank_connector_satisfies_the_protocol() -> None:
    bank: BankConnector = connector(lambda _: httpx.Response(200, json=[]))
    assert bank is not None


def test_list_accounts() -> None:
    accounts = [{"account_id": "acc-1", "display_name": "Main", "currency": "EUR"}]
    sent: list[httpx.Request] = []

    result = connector(recording(httpx.Response(200, json=accounts), sent)).list_accounts()

    assert result == accounts
    assert sent[0].method == "GET"
    assert sent[0].url == f"{BASE_URL}/v1/accounts"
    assert sent[0].headers["X-API-Key"] == API_KEY


def test_get_balance_keeps_the_amount_string() -> None:
    balance = {"account_id": "acc-1", "balance": "1234.50", "currency": "EUR", "as_of": "x"}
    sent: list[httpx.Request] = []

    result = connector(recording(httpx.Response(200, json=balance), sent)).get_balance("acc-1")

    assert result == balance
    assert result["balance"] == "1234.50"
    assert sent[0].url == f"{BASE_URL}/v1/accounts/acc-1/balance"
    assert sent[0].headers["X-API-Key"] == API_KEY


def test_first_page_sends_no_cursor_and_keeps_records_unchanged() -> None:
    body = {"transactions": [TRANSACTION], "next_cursor": "c-1", "has_more": True}
    sent: list[httpx.Request] = []

    page = connector(recording(httpx.Response(200, json=body), sent)).fetch_transactions(
        "acc-1", None, 100
    )

    assert page == TransactionPage(records=[TRANSACTION], next_cursor="c-1", has_more=True)
    assert page.records[0]["amount"] == "1234.50"
    assert sent[0].url.path == "/v1/accounts/acc-1/transactions"
    assert dict(sent[0].url.params) == {"limit": "100"}
    assert sent[0].headers["X-API-Key"] == API_KEY


def test_last_page_sends_the_cursor() -> None:
    body = {"transactions": [], "next_cursor": "c-2", "has_more": False}
    sent: list[httpx.Request] = []

    page = connector(recording(httpx.Response(200, json=body), sent)).fetch_transactions(
        "acc-1", "c-2", 50
    )

    assert page == TransactionPage(records=[], next_cursor="c-2", has_more=False)
    assert dict(sent[0].url.params) == {"limit": "50", "cursor": "c-2"}


@pytest.mark.parametrize("limit", [0, 501])
def test_limit_out_of_range_sends_no_request(limit: int) -> None:
    sent: list[httpx.Request] = []
    bank = connector(recording(httpx.Response(200), sent))

    with pytest.raises(ValueError):
        bank.fetch_transactions("acc-1", None, limit)
    assert sent == []


@pytest.mark.parametrize("limit", [1, 500])
def test_limit_at_the_bounds_is_accepted(limit: int) -> None:
    body: dict[str, Any] = {"transactions": [], "next_cursor": None, "has_more": False}
    sent: list[httpx.Request] = []

    connector(recording(httpx.Response(200, json=body), sent)).fetch_transactions(
        "acc-1", None, limit
    )

    assert sent[0].url.params["limit"] == str(limit)


def raising(exc: Exception) -> Handler:
    def handler(request: httpx.Request) -> httpx.Response:
        raise exc

    return handler


ERROR_CASES: list[tuple[str, Handler, str]] = [
    ("unauthorized", lambda _: httpx.Response(401, json={"detail": BODY_MARKER}), ""),
    ("account_not_found", lambda _: httpx.Response(404, json={"error": BODY_MARKER}), ""),
    ("invalid_cursor", lambda _: httpx.Response(400, json={"error": "invalid_cursor"}), ""),
    ("http_error", lambda _: httpx.Response(400, json={"error": BODY_MARKER}), "400"),
    ("http_error", lambda _: httpx.Response(503, text=BODY_MARKER), "503"),
    ("timeout", raising(httpx.ReadTimeout(BODY_MARKER)), ""),
    ("connection", raising(httpx.ConnectError(BODY_MARKER)), ""),
    ("invalid_response", lambda _: httpx.Response(200, text=BODY_MARKER), ""),
    (
        "invalid_response",
        lambda _: httpx.Response(
            200, headers={"Content-Encoding": "gzip"}, content=BODY_MARKER.encode()
        ),
        "",
    ),
    (
        "invalid_response",
        lambda _: httpx.Response(200, json={"transactions": [], "next_cursor": BODY_MARKER}),
        "",
    ),
]


@pytest.mark.parametrize(("kind", "handler", "in_message"), ERROR_CASES)
def test_failures_raise_connector_error_without_secrets(
    kind: str, handler: Handler, in_message: str
) -> None:
    with pytest.raises(ConnectorError) as caught:
        connector(handler).fetch_transactions("acc-1", "c-1", 10)

    error = caught.value
    assert error.kind == kind
    assert in_message in str(error)
    for text in (str(error), repr(error)):
        assert API_KEY not in text
        assert BODY_MARKER not in text
    assert error.__cause__ is None
    assert error.__context__ is None


@pytest.mark.parametrize(
    ("method", "body"),
    [("list_accounts", {"not": "a list"}), ("get_balance", ["not", "a dict"])],
)
def test_unexpected_shape_is_invalid_response(method: str, body: Any) -> None:
    bank = connector(lambda _: httpx.Response(200, json=body))
    call = bank.list_accounts if method == "list_accounts" else lambda: bank.get_balance("a")

    with pytest.raises(ConnectorError) as caught:
        call()
    assert caught.value.kind == "invalid_response"


def test_from_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost/db")
    monkeypatch.setenv("DEMOBANK_API_KEY", API_KEY)
    monkeypatch.setenv("DEMOBANK_BASE_URL", BASE_URL)
    bank = DemoBankConnector.from_settings(Settings())

    assert bank._client.base_url == BASE_URL
    assert bank._client.headers["X-API-Key"] == API_KEY
    assert bank._client.timeout == httpx.Timeout(10.0, connect=3.0)


def test_gzip_header_with_a_body_that_is_not_gzip_is_invalid_response() -> None:
    bank = connector(
        lambda _: httpx.Response(
            200, headers={"Content-Encoding": "gzip"}, content=BODY_MARKER.encode()
        )
    )

    with pytest.raises(ConnectorError) as caught:
        bank.list_accounts()
    assert caught.value.kind == "invalid_response"
    assert caught.value.__context__ is None
