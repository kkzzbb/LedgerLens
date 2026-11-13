"""The sync service (#21) and `POST /api/sync`, with a fake connector and session.

The repository functions are replaced by fakes that keep rows in memory, so no
database is needed. `tests/db/test_sync.py` runs the real thing on PostgreSQL.
"""

import logging
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Self, cast

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from ledgerlens.api import sync as sync_api
from ledgerlens.api.app import create_app
from ledgerlens.config import Settings, get_settings
from ledgerlens.connectors.base import ConnectorError, TransactionPage
from ledgerlens.db.models import BankAccount
from ledgerlens.db.repositories.bank import InsertResult
from ledgerlens.domain.normalization import NormalizedTransaction
from ledgerlens.services import sync
from ledgerlens.services.sync import AccountSyncResult, AnomalyRuleResult, SyncResult, run_sync
from ledgerlens.sync import main as cli_main

NOW = datetime(2026, 11, 12, 10, 0, tzinfo=UTC)
AS_OF = "2026-11-12T09:59:00Z"
SECRET_MARKER = "MARKER-secret"


def record(transaction_id: str, account_id: str = "acc-1", **overrides: Any) -> dict[str, Any]:
    raw: dict[str, Any] = {
        "transaction_id": transaction_id,
        "account_id": account_id,
        "booking_date": "2026-11-01",
        "amount": "12.34",
        "currency": "EUR",
        "direction": "debit",
        "status": "booked",
    }
    raw.update(overrides)
    return raw


Step = TransactionPage | ConnectorError


@dataclass
class FakeConnector:
    """Implements `BankConnector`; pages and balances are scripted per account."""

    accounts: list[str] = field(default_factory=lambda: ["acc-1"])
    pages: dict[str, list[Step]] = field(default_factory=dict)
    balances: dict[str, dict[str, Any] | ConnectorError] = field(default_factory=dict)
    list_error: ConnectorError | None = None
    calls: list[tuple[str, str | None, int]] = field(default_factory=list)

    def list_accounts(self) -> list[dict[str, Any]]:
        if self.list_error is not None:
            raise self.list_error
        return [
            {"account_id": a, "display_name": a.upper(), "currency": "EUR"} for a in self.accounts
        ]

    def get_balance(self, account_id: str) -> dict[str, Any]:
        balance = self.balances.get(account_id, {"balance": "100.50", "as_of": AS_OF})
        if isinstance(balance, ConnectorError):
            raise balance
        return balance

    def fetch_transactions(
        self, account_id: str, cursor: str | None, limit: int
    ) -> TransactionPage:
        self.calls.append((account_id, cursor, limit))
        steps = self.pages.get(account_id, [])
        step = steps.pop(0) if steps else TransactionPage([], None, False)
        if isinstance(step, ConnectorError):
            raise step
        return step


@dataclass
class Store:
    accounts: dict[int, BankAccount] = field(default_factory=dict)
    transactions: dict[str, NormalizedTransaction] = field(default_factory=dict)
    # (rule, today, transactions stored when it ran)
    rule_calls: list[tuple[str, date, int]] = field(default_factory=list)


class FakeSession:
    def __init__(self, store: Store) -> None:
        self.store = store

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def begin(self) -> "FakeSession":
        return self

    def get_one(self, model: type[BankAccount], ident: int) -> BankAccount:
        return self.store.accounts[ident]


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> Store:
    """In-memory rows behind the repository functions the service calls."""
    return fake_repositories(monkeypatch)


def fake_repositories(monkeypatch: pytest.MonkeyPatch) -> Store:
    """Replaces the repository functions the service calls with in-memory fakes."""
    data = Store()

    def upsert(
        session: FakeSession, provider: str, external_id: str, name: str, currency: str
    ) -> BankAccount:
        for account in data.accounts.values():
            if account.external_account_id == external_id:
                account.display_name = name
                return account
        account = BankAccount(
            id=len(data.accounts) + 1,
            provider=provider,
            external_account_id=external_id,
            display_name=name,
            currency=currency,
            last_cursor=None,
        )
        data.accounts[account.id] = account
        return account

    def insert(
        session: FakeSession, account: BankAccount, batch: list[NormalizedTransaction]
    ) -> InsertResult:
        assert all(t.external_account_id == account.external_account_id for t in batch)
        created: list[int] = []
        for transaction in batch:
            if transaction.external_transaction_id not in data.transactions:
                data.transactions[transaction.external_transaction_id] = transaction
                created.append(len(data.transactions))
        return InsertResult(created, len(created), len(batch) - len(created))

    monkeypatch.setattr(sync, "upsert_bank_account", upsert)
    monkeypatch.setattr(sync, "insert_new_transactions", insert)
    monkeypatch.setattr(sync, "categorize_transactions", lambda session, account_id: 0)

    def rule(name: str) -> Any:
        def flag(session: FakeSession, today: date, *thresholds: object) -> int:
            data.rule_calls.append((name, today, len(data.transactions)))
            return 1

        return flag

    monkeypatch.setattr(sync, "flag_possible_duplicates", rule("possible_duplicate"))
    monkeypatch.setattr(sync, "flag_large_expenses", rule("large_expense"))
    return data


def factory(store: Store) -> sync.SessionFactory:
    return lambda: cast(Session, FakeSession(store))


def run_all(connector: FakeConnector, store: Store, page_size: int = 2) -> SyncResult:
    settings = Settings.model_construct(sync_page_size=page_size)
    return run_sync(connector, factory(store), lambda: NOW, settings)


def run(connector: FakeConnector, store: Store, page_size: int = 2) -> list[AccountSyncResult]:
    return run_all(connector, store, page_size).accounts


def page(*records: dict[str, Any], cursor: str | None, more: bool = False) -> TransactionPage:
    return TransactionPage(list(records), cursor, more)


# Success


def test_two_pages_are_stored_and_the_account_row_updated(store: Store) -> None:
    connector = FakeConnector(
        pages={
            "acc-1": [
                page(record("t1"), record("t2"), cursor="c1", more=True),
                page(record("t3"), cursor="c2"),
            ]
        }
    )

    [result] = run(connector, store)

    assert connector.calls == [("acc-1", None, 2), ("acc-1", "c1", 2)]
    assert (result.status, result.created_count, result.rejected_count) == ("succeeded", 3, 0)
    assert result.error is None
    assert len(result.created_ids) == 3
    account = store.accounts[1]
    assert account.last_cursor == "c2"
    assert account.last_balance == Decimal("100.50")
    assert account.last_balance_at == datetime(2026, 11, 12, 9, 59, tzinfo=UTC)
    assert account.last_sync_at == account.last_successful_sync_at == NOW
    assert (account.last_sync_status, account.last_sync_error) == ("succeeded", None)


def test_run_without_new_records_succeeds_and_keeps_the_cursor(store: Store) -> None:
    run(FakeConnector(pages={"acc-1": [page(record("t1"), cursor="c1")]}), store)
    store.accounts[1].last_successful_sync_at = None
    connector = FakeConnector(pages={"acc-1": [page(cursor=None)]})

    [result] = run(connector, store)

    assert connector.calls == [("acc-1", "c1", 2)]
    assert (result.status, result.created_count) == ("succeeded", 0)
    assert store.accounts[1].last_cursor == "c1"
    assert store.accounts[1].last_successful_sync_at == NOW


# Rejections


def test_rejections_are_counted_by_code_and_valid_records_stored(store: Store) -> None:
    bad_amount = "MARKER-not-an-amount"
    connector = FakeConnector(
        pages={
            "acc-1": [
                page(
                    record("t1"),
                    record("t2", amount=bad_amount),
                    record("t3", amount="-1.00"),
                    record("t4", account_id="acc-other"),
                    cursor="c1",
                )
            ]
        }
    )

    [result] = run(connector, store)

    expected = "rejected: account_mismatch=1, invalid_amount=2"
    assert (result.status, result.created_count, result.rejected_count) == (
        "succeeded_with_errors",
        1,
        3,
    )
    assert result.error == expected
    assert list(store.transactions) == ["t1"]
    account = store.accounts[1]
    assert (account.last_sync_status, account.last_sync_error) == (
        "succeeded_with_errors",
        expected,
    )
    assert account.last_cursor == "c1"
    assert bad_amount not in expected


# Connector errors


def test_error_on_page_two_stores_nothing_and_records_the_failure(store: Store) -> None:
    connector = FakeConnector(
        accounts=["acc-1", "acc-2"],
        pages={
            "acc-1": [page(record("t1"), cursor="c1", more=True), ConnectorError("timeout", "x")],
            "acc-2": [page(record("u1", account_id="acc-2"), cursor="d1")],
        },
    )

    first, second = run(connector, store)

    assert (first.status, first.error, first.created_count) == ("failed", "timeout", 0)
    assert "t1" not in store.transactions
    account = store.accounts[1]
    assert account.last_cursor is None
    assert account.last_balance is None
    assert account.last_successful_sync_at is None
    assert (account.last_sync_status, account.last_sync_at, account.last_sync_error) == (
        "failed",
        NOW,
        "timeout",
    )
    assert (second.status, second.created_count) == ("succeeded", 1)


def test_error_from_get_balance_fails_the_account(store: Store) -> None:
    connector = FakeConnector(
        pages={"acc-1": [page(record("t1"), cursor="c1")]},
        balances={"acc-1": ConnectorError("http_error", "x")},
    )

    [result] = run(connector, store)

    assert (result.status, result.error) == ("failed", "http_error")
    assert store.transactions == {}
    assert store.accounts[1].last_cursor is None


@pytest.mark.parametrize(
    "balance",
    [
        {"balance": "MARKER", "as_of": AS_OF},
        {"balance": 100.5, "as_of": AS_OF},
        {"balance": "100.50", "as_of": "MARKER"},
        {"balance": "100.50", "as_of": "2026-11-12T09:59:00"},
        {"balance": "100.50"},
    ],
    ids=["bad-amount", "float", "bad-as-of", "naive-as-of", "missing-as-of"],
)
def test_invalid_balance_is_an_invalid_response(store: Store, balance: dict[str, Any]) -> None:
    connector = FakeConnector(balances={"acc-1": balance})

    [result] = run(connector, store)

    assert (result.status, result.error) == ("failed", "invalid_response")
    assert store.accounts[1].last_sync_error == "invalid_response"


# Anomaly rules


def test_rules_run_once_after_all_accounts_with_today_from_now(store: Store) -> None:
    connector = FakeConnector(
        accounts=["acc-1", "acc-2"],
        pages={
            "acc-1": [page(record("t1"), cursor="c1")],
            "acc-2": [ConnectorError("timeout", "x")],
        },
    )

    result = run_all(connector, store)

    today = NOW.date()
    assert store.rule_calls == [("possible_duplicate", today, 1), ("large_expense", today, 1)]
    assert result.anomalies == [
        AnomalyRuleResult("possible_duplicate", 1, None),
        AnomalyRuleResult("large_expense", 1, None),
    ]


def test_rules_do_not_run_when_listing_fails(store: Store) -> None:
    connector = FakeConnector(list_error=ConnectorError("unauthorized", "x"))

    with pytest.raises(ConnectorError):
        run_all(connector, store)
    assert store.rule_calls == []


def failing_rule(session: FakeSession, today: date, *thresholds: object) -> int:
    raise ValueError(SECRET_MARKER)


def test_a_failing_rule_is_recorded_and_the_other_still_runs(
    store: Store, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(sync, "flag_possible_duplicates", failing_rule)
    connector = FakeConnector(pages={"acc-1": [page(record("t1"), cursor="c1")]})

    with caplog.at_level(logging.WARNING):
        result = run_all(connector, store)

    assert result.anomalies == [
        AnomalyRuleResult("possible_duplicate", 0, "ValueError"),
        AnomalyRuleResult("large_expense", 1, None),
    ]
    assert [name for name, _, _ in store.rule_calls] == ["large_expense"]
    assert list(store.transactions) == ["t1"]
    assert store.accounts[1].last_sync_status == "succeeded"
    assert "possible_duplicate" in caplog.text
    assert "ValueError" in caplog.text
    assert SECRET_MARKER not in caplog.text


# POST /api/sync


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[Settings]:
    monkeypatch.setenv("DATABASE_URL", f"postgresql://u:{SECRET_MARKER}@localhost/x")
    monkeypatch.setenv("DEMOBANK_API_KEY", SECRET_MARKER)
    get_settings.cache_clear()
    yield get_settings()
    get_settings.cache_clear()


def client(connector: FakeConnector, store: Store) -> TestClient:
    app = create_app()
    app.dependency_overrides[sync_api.get_connector] = lambda: connector
    app.dependency_overrides[sync_api.get_session_factory] = lambda: factory(store)
    return TestClient(app)


@pytest.mark.usefixtures("settings")
def test_post_sync_returns_one_result_per_account(store: Store) -> None:
    connector = FakeConnector(
        accounts=["acc-1", "acc-2"],
        pages={
            "acc-1": [page(record("t1"), cursor="c1")],
            "acc-2": [ConnectorError("timeout", "x")],
        },
    )

    response = client(connector, store).post("/api/sync")

    assert response.status_code == 200
    assert response.json() == {
        "accounts": [
            {
                "account_id": 1,
                "external_account_id": "acc-1",
                "status": "succeeded",
                "created_count": 1,
                "skipped_count": 0,
                "rejected_count": 0,
                "error": None,
            },
            {
                "account_id": 2,
                "external_account_id": "acc-2",
                "status": "failed",
                "created_count": 0,
                "skipped_count": 0,
                "rejected_count": 0,
                "error": "timeout",
            },
        ],
        "anomalies": [
            {"rule": "possible_duplicate", "created_count": 1, "error": None},
            {"rule": "large_expense", "created_count": 1, "error": None},
        ],
    }
    assert SECRET_MARKER not in response.text


@pytest.mark.usefixtures("settings")
def test_post_sync_returns_200_when_a_rule_fails(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sync, "flag_large_expenses", failing_rule)

    response = client(FakeConnector(), store).post("/api/sync")

    assert response.status_code == 200
    assert response.json()["anomalies"] == [
        {"rule": "possible_duplicate", "created_count": 1, "error": None},
        {"rule": "large_expense", "created_count": 0, "error": "ValueError"},
    ]
    assert SECRET_MARKER not in response.text


@pytest.mark.usefixtures("settings")
def test_post_sync_returns_502_when_listing_fails(store: Store) -> None:
    connector = FakeConnector(list_error=ConnectorError("unauthorized", "x"))

    response = client(connector, store).post("/api/sync")

    assert response.status_code == 502
    assert response.json() == {"detail": "unauthorized"}
    assert store.accounts == {}


# uv run python -m ledgerlens.sync


@pytest.fixture
def cli(
    settings: Settings, store: Store, monkeypatch: pytest.MonkeyPatch
) -> Iterator[FakeConnector]:
    """`main()` with the fake connector and session."""
    connector = FakeConnector(pages={"acc-1": [page(record("t1"), cursor="c1")]})

    class Connector:
        @staticmethod
        def from_settings(settings: Settings) -> Any:
            return connector

    monkeypatch.setattr(FakeConnector, "__enter__", lambda self: self, raising=False)
    monkeypatch.setattr(FakeConnector, "__exit__", lambda self, *args: None, raising=False)
    monkeypatch.setattr("ledgerlens.sync.DemoBankConnector", Connector)
    monkeypatch.setattr("ledgerlens.sync.get_sessionmaker", lambda: factory(store))
    yield connector


def test_cli_prints_one_line_per_rule_after_the_accounts(
    cli: FakeConnector, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli_main() == 0
    assert capsys.readouterr().out.splitlines() == [
        "acc-1 succeeded created=1 rejected=0",
        "anomalies possible_duplicate created=1",
        "anomalies large_expense created=1",
    ]


def test_cli_exit_status_ignores_a_failed_rule(
    cli: FakeConnector, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sync, "flag_possible_duplicates", failing_rule)

    assert cli_main() == 0
    assert capsys.readouterr().out.splitlines()[1:] == [
        "anomalies possible_duplicate created=0 error=ValueError",
        "anomalies large_expense created=1",
    ]
