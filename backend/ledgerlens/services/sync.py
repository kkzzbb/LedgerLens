"""One synchronization of every bank account, run on demand.

`run_sync` upserts the accounts the connector lists, then syncs each account
on its own: it fetches the pages after the stored cursor, normalizes the
records, reads the balance and stores everything in one transaction, where
every uncategorized transaction of the account also gets its category. A
`ConnectorError` stores nothing of that account's run and records the failure
in a separate transaction; the other accounts are still synced.

After every account, the two anomaly rules run once over all accounts, each in
its own transaction. A rule that raises rolls back only its own flags: the
result records the exception class name and the sync goes on.

Telemetry (#122), through the `opentelemetry-api` only (a no-op until the
application installs providers): one `sync account` span per account, one
`anomaly rule` span per rule, the `ledgerlens.sync` metrics and one
`sync finished` (or `sync failed`) log line per run. Every attribute is a
status, an outcome, a rule name, an error kind or a count: never an account
id, a transaction field or an amount.

The account row is the only sync record (`docs/scope.md`): no job table, no
retry. `last_sync_error` holds an error kind or rejection counts, never a field
value, a response body or a secret.
"""

import logging
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Final

from opentelemetry import metrics, trace
from opentelemetry.trace import Span, StatusCode
from sqlalchemy.orm import Session

from ledgerlens.config import Settings
from ledgerlens.connectors.base import BankConnector, ConnectorError
from ledgerlens.db.models import BankAccount
from ledgerlens.db.repositories.anomalies import flag_large_expenses, flag_possible_duplicates
from ledgerlens.db.repositories.bank import (
    categorize_transactions,
    insert_new_transactions,
    upsert_bank_account,
)
from ledgerlens.domain.money import Money
from ledgerlens.domain.normalization import NormalizedTransaction, normalize_batch

PROVIDER: Final = "demobank"
SUCCEEDED: Final = "succeeded"
SUCCEEDED_WITH_ERRORS: Final = "succeeded_with_errors"
FAILED: Final = "failed"
ACCOUNT_MISMATCH: Final = "account_mismatch"

logger = logging.getLogger(__name__)
tracer = trace.get_tracer("ledgerlens.sync")
meter = metrics.get_meter("ledgerlens.sync")

# In Prometheus: ledgerlens_sync_runs_total{outcome}, ledgerlens_sync_duration_seconds_*,
# ledgerlens_sync_transactions_total{result} and ledgerlens_anomaly_flags_total{rule}.
sync_runs = meter.create_counter(
    "ledgerlens.sync.runs", description="Sync runs, by outcome (succeeded, ...)"
)
sync_duration = meter.create_histogram(
    "ledgerlens.sync.duration", unit="s", description="Duration of a sync run, by outcome"
)
sync_transactions = meter.create_counter(
    "ledgerlens.sync.transactions",
    description="Transactions a sync run created, skipped or rejected",
)
anomaly_flags = meter.create_counter(
    "ledgerlens.anomaly.flags", description="Anomaly flags created, by rule"
)

Now = Callable[[], datetime]
SessionFactory = Callable[[], Session]


@dataclass(frozen=True)
class AccountSyncResult:
    bank_account_id: int
    external_account_id: str
    status: str
    created_count: int
    skipped_count: int
    rejected_count: int
    error: str | None
    created_ids: list[int]


@dataclass(frozen=True)
class AnomalyRuleResult:
    rule: str
    created_count: int
    error: str | None


@dataclass(frozen=True)
class SyncResult:
    accounts: list[AccountSyncResult]
    anomalies: list[AnomalyRuleResult]


@dataclass(frozen=True)
class _Account:
    id: int
    external_account_id: str
    last_cursor: str | None


@dataclass(frozen=True)
class _Fetched:
    records: list[dict[str, Any]]
    cursor: str | None
    balance: Decimal
    balance_at: datetime


def utc_now() -> datetime:
    """The current time, timezone-aware UTC."""
    return datetime.now(UTC)


def run_sync(
    connector: BankConnector,
    session_factory: SessionFactory,
    now: Now,
    settings: Settings,
) -> SyncResult:
    """Syncs every account once, then runs the anomaly rules once.

    A `ConnectorError` from `list_accounts()` propagates, and no rule runs.
    Every run, also one that raises, is counted in the `ledgerlens.sync`
    metrics with its outcome.
    """
    started = time.perf_counter()
    outcome = FAILED
    try:
        result = _run(connector, session_factory, now, settings)
    except ConnectorError as error:
        _failed(error.kind)
        raise
    except Exception as error:
        _failed(type(error).__name__)
        raise
    else:
        outcome = run_outcome(result)
        _finished(result, outcome)
        return result
    finally:
        sync_runs.add(1, {"outcome": outcome})
        sync_duration.record(time.perf_counter() - started, {"outcome": outcome})


def run_outcome(result: SyncResult) -> str:
    """`failed` when every listed account failed, `succeeded_with_errors` when
    an account or a rule failed, `succeeded` otherwise (also with no account)."""
    failed_accounts = sum(account.status == FAILED for account in result.accounts)
    if result.accounts and failed_accounts == len(result.accounts):
        return FAILED
    if failed_accounts or any(rule.error is not None for rule in result.anomalies):
        return SUCCEEDED_WITH_ERRORS
    return SUCCEEDED


def _finished(result: SyncResult, outcome: str) -> None:
    created = sum(account.created_count for account in result.accounts)
    skipped = sum(account.skipped_count for account in result.accounts)
    rejected = sum(account.rejected_count for account in result.accounts)
    flags = sum(rule.created_count for rule in result.anomalies)
    for name, count in (("created", created), ("skipped", skipped), ("rejected", rejected)):
        sync_transactions.add(count, {"result": name})
    for rule in result.anomalies:
        anomaly_flags.add(rule.created_count, {"rule": rule.rule})
    # Counts only. `created` is a reserved `LogRecord` attribute, hence `*_count`.
    logger.info(
        "sync finished",
        extra={
            "outcome": outcome,
            "accounts": len(result.accounts),
            "created_count": created,
            "skipped_count": skipped,
            "rejected_count": rejected,
            "flags": flags,
        },
    )


def _failed(kind: str) -> None:
    """Marks the current (request) span and logs the error kind, never a value."""
    span = trace.get_current_span()
    span.set_attribute("ledgerlens.sync.error_kind", kind)
    span.set_status(StatusCode.ERROR, kind)
    logger.warning("sync failed: %s", kind, extra={"outcome": FAILED, "error_kind": kind})


def _run(
    connector: BankConnector,
    session_factory: SessionFactory,
    now: Now,
    settings: Settings,
) -> SyncResult:
    listed = connector.list_accounts()
    with session_factory() as session, session.begin():
        accounts = [_upsert(session, record) for record in listed]
    results = [
        _sync_account(connector, session_factory, now, settings.sync_page_size, a) for a in accounts
    ]
    today = now().date()
    anomalies = [_run_rule(session_factory, name, rule, today, settings) for name, rule in _rules()]
    return SyncResult(results, anomalies)


Rule = Callable[[Session, date, Settings], int]


def _rules() -> list[tuple[str, Rule]]:
    """The rules in run order. Looked up at call time so tests can replace them."""

    def duplicates(session: Session, today: date, settings: Settings) -> int:
        return flag_possible_duplicates(
            session,
            today,
            settings.anomaly_evaluation_window_days,
            settings.anomaly_duplicate_window_days,
            settings.anomaly_duplicate_amount_tolerance_percent,
        )

    def large_expenses(session: Session, today: date, settings: Settings) -> int:
        return flag_large_expenses(
            session,
            today,
            settings.anomaly_evaluation_window_days,
            settings.anomaly_large_expense_absolute,
            settings.anomaly_large_expense_multiplier,
            settings.anomaly_min_history_count,
            settings.anomaly_baseline_days,
        )

    return [("possible_duplicate", duplicates), ("large_expense", large_expenses)]


def _run_rule(
    session_factory: SessionFactory, name: str, rule: Rule, today: date, settings: Settings
) -> AnomalyRuleResult:
    with tracer.start_as_current_span(
        "anomaly rule",
        attributes={"ledgerlens.anomaly.rule": name},
        record_exception=False,
        set_status_on_exception=False,
    ) as span:
        result = _apply_rule(session_factory, name, rule, today, settings)
        span.set_attribute("ledgerlens.anomaly.created_count", result.created_count)
        if result.error is not None:
            span.set_status(StatusCode.ERROR, result.error)
        return result


def _apply_rule(
    session_factory: SessionFactory, name: str, rule: Rule, today: date, settings: Settings
) -> AnomalyRuleResult:
    try:
        with session_factory() as session, session.begin():
            created = rule(session, today, settings)
    except Exception as error:  # a rule failure must not fail the sync
        kind = type(error).__name__
    else:
        return AnomalyRuleResult(name, created, None)
    # Class name only: the message may hold values.
    logger.warning("anomaly rule %s failed: %s", name, kind)
    return AnomalyRuleResult(name, 0, kind)


def _text(record: dict[str, Any], key: str) -> str:
    value = record.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConnectorError("invalid_response", "the bank sent an unexpected account")
    return value


def _upsert(session: Session, record: dict[str, Any]) -> _Account:
    account = upsert_bank_account(
        session,
        PROVIDER,
        _text(record, "account_id"),
        _text(record, "display_name"),
        _text(record, "currency"),
    )
    return _Account(account.id, account.external_account_id, account.last_cursor)


def _sync_account(
    connector: BankConnector,
    session_factory: SessionFactory,
    now: Now,
    page_size: int,
    account: _Account,
) -> AccountSyncResult:
    # No account id on the span: only the status and the counts.
    with tracer.start_as_current_span(
        "sync account", record_exception=False, set_status_on_exception=False
    ) as span:
        result = _sync_one_account(connector, session_factory, now, page_size, account)
        _annotate(span, result)
        return result


def _annotate(span: Span, result: AccountSyncResult) -> None:
    span.set_attribute("ledgerlens.sync.status", result.status)
    span.set_attribute("ledgerlens.sync.created_count", result.created_count)
    span.set_attribute("ledgerlens.sync.skipped_count", result.skipped_count)
    span.set_attribute("ledgerlens.sync.rejected_count", result.rejected_count)
    if result.status == FAILED and result.error is not None:
        span.set_status(StatusCode.ERROR, result.error)


def _sync_one_account(
    connector: BankConnector,
    session_factory: SessionFactory,
    now: Now,
    page_size: int,
    account: _Account,
) -> AccountSyncResult:
    try:
        fetched = _fetch(connector, account, page_size)
    except ConnectorError as error:
        with session_factory() as session, session.begin():
            row = session.get_one(BankAccount, account.id)
            row.last_sync_status = FAILED
            row.last_sync_at = now()
            row.last_sync_error = error.kind
        return AccountSyncResult(
            account.id, account.external_account_id, FAILED, 0, 0, 0, error.kind, []
        )

    accepted, rejections = normalize_batch(fetched.records)
    matching: list[NormalizedTransaction] = []
    codes = Counter(rejection.code for rejection in rejections)
    for transaction in accepted:
        if transaction.external_account_id == account.external_account_id:
            matching.append(transaction)
        else:
            codes[ACCOUNT_MISMATCH] += 1
    status, error_text = (SUCCEEDED_WITH_ERRORS, _summary(codes)) if codes else (SUCCEEDED, None)

    with session_factory() as session, session.begin():
        row = session.get_one(BankAccount, account.id)
        inserted = insert_new_transactions(session, row, matching)
        # Also covers rows stored before the category column existed.
        categorize_transactions(session, row.id)
        timestamp = now()
        row.last_cursor = fetched.cursor
        row.last_balance = fetched.balance
        row.last_balance_at = fetched.balance_at
        row.last_sync_at = timestamp
        row.last_successful_sync_at = timestamp
        row.last_sync_status = status
        row.last_sync_error = error_text
    return AccountSyncResult(
        bank_account_id=account.id,
        external_account_id=account.external_account_id,
        status=status,
        created_count=inserted.created_count,
        skipped_count=inserted.skipped_count,
        rejected_count=codes.total(),
        error=error_text,
        created_ids=inserted.created_ids,
    )


def _fetch(connector: BankConnector, account: _Account, page_size: int) -> _Fetched:
    """Every page after the stored cursor, then the balance. Raises `ConnectorError`."""
    records: list[dict[str, Any]] = []
    cursor = account.last_cursor
    while True:
        page = connector.fetch_transactions(account.external_account_id, cursor, page_size)
        records.extend(page.records)
        if page.next_cursor is not None:
            cursor = page.next_cursor
        if not page.has_more:
            break
        if page.next_cursor is None:
            # More pages but no cursor to ask for them: it would loop forever.
            raise ConnectorError("invalid_response", "the bank sent a page without a cursor")
    balance, balance_at = _balance(connector.get_balance(account.external_account_id))
    return _Fetched(records, cursor, balance, balance_at)


def _balance(record: dict[str, Any]) -> tuple[Decimal, datetime]:
    amount = record.get("balance")
    as_of = record.get("as_of")
    parsed: tuple[Decimal, datetime] | None = None
    if isinstance(amount, str) and isinstance(as_of, str):
        try:
            parsed = (Money(amount).amount, datetime.fromisoformat(as_of))
        except ValueError:
            parsed = None
    # Raised outside the `except` block: the ValueError message holds the value.
    if parsed is None or parsed[1].tzinfo is None:
        raise ConnectorError("invalid_response", "the bank sent an unexpected balance")
    return parsed


def _summary(codes: Counter[str]) -> str:
    """`rejected: account_mismatch=1, invalid_amount=2`, sorted by code."""
    return "rejected: " + ", ".join(f"{code}={count}" for code, count in sorted(codes.items()))
