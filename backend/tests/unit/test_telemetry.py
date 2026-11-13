"""Traces, metrics and JSON logs of the sync (#122), with in-memory exporters.

`POST /api/sync` runs through `TestClient` with the real DemoBank connector,
whose requests go through the httpx instrumentation to a fake DemoBank
(`MockedHTTPTransport`). The repository functions are the in-memory fakes of
`test_sync_service.py`, so no database is needed.
"""

import logging
import os
import re
import threading
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from opentelemetry import trace
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.trace import SpanKind, StatusCode

from ledgerlens import telemetry
from ledgerlens.api import sync as sync_api
from ledgerlens.api.app import create_app
from ledgerlens.config import Settings, get_settings
from ledgerlens.connectors.demobank import DemoBankConnector
from ledgerlens.services import sync
from ledgerlens.services.sync import AccountSyncResult, AnomalyRuleResult, SyncResult
from tests.telemetry_support import (
    DEMOBANK_URL,
    SENTINEL_API_KEY,
    Handler,
    InMemoryTelemetry,
    MockedHTTPTransport,
    fake_demobank,
    json_lines,
    raising,
    requests_seen,
)
from tests.unit.test_sync_service import Store, factory, failing_rule, fake_repositories


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> Store:
    """The in-memory repositories of `test_sync_service.py`."""
    return fake_repositories(monkeypatch)


ROUTE = "POST /api/sync"


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[Settings]:
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:pw@localhost/x")
    monkeypatch.setenv("DEMOBANK_API_KEY", SENTINEL_API_KEY)
    monkeypatch.setenv("SYNC_PAGE_SIZE", "1")
    get_settings.cache_clear()
    yield get_settings()
    get_settings.cache_clear()


def client(store: Store, handler: Handler = fake_demobank) -> TestClient:
    app = create_app()

    def connector() -> Iterator[DemoBankConnector]:
        transport = MockedHTTPTransport(handler)
        with DemoBankConnector(DEMOBANK_URL, SENTINEL_API_KEY, transport=transport) as built:
            yield built

    app.dependency_overrides[sync_api.get_connector] = connector
    app.dependency_overrides[sync_api.get_session_factory] = lambda: factory(store)
    return TestClient(app)


def by_name(spans: list[ReadableSpan], name: str) -> list[ReadableSpan]:
    return [span for span in spans if span.name == name]


def server_span(spans: list[ReadableSpan]) -> ReadableSpan:
    [span] = [s for s in spans if s.kind is SpanKind.SERVER]
    return span


def attributes(span: ReadableSpan) -> dict[str, Any]:
    return dict(span.attributes or {})


# Traces


@pytest.mark.usefixtures("settings")
def test_one_sync_is_one_trace_with_client_and_custom_spans(
    otel: InMemoryTelemetry, store: Store
) -> None:
    response = client(store).post("/api/sync")

    assert response.status_code == 200
    spans = otel.finished_spans()
    root = server_span(spans)
    assert root.name == ROUTE
    assert root.parent is None
    assert root.resource.attributes["service.name"] == "ledgerlens-backend"
    assert {span.context.trace_id for span in spans} == {root.context.trace_id}

    clients = [span for span in spans if span.kind is SpanKind.CLIENT]
    # The account list, two transaction pages, the balance.
    assert [span.name for span in clients] == ["GET"] * 4
    paths = sorted(str(attributes(span)["url.full"]) for span in clients)
    assert paths == [
        f"{DEMOBANK_URL}/v1/accounts",
        f"{DEMOBANK_URL}/v1/accounts/acc_operating_001/balance",
        f"{DEMOBANK_URL}/v1/accounts/acc_operating_001/transactions",
        f"{DEMOBANK_URL}/v1/accounts/acc_operating_001/transactions",
    ]

    [account] = by_name(spans, "sync account")
    assert attributes(account) == {
        "ledgerlens.sync.status": "succeeded",
        "ledgerlens.sync.created_count": 2,
        "ledgerlens.sync.skipped_count": 0,
        "ledgerlens.sync.rejected_count": 0,
    }
    rules = by_name(spans, "anomaly rule")
    assert [attributes(span) for span in rules] == [
        {"ledgerlens.anomaly.rule": "possible_duplicate", "ledgerlens.anomaly.created_count": 1},
        {"ledgerlens.anomaly.rule": "large_expense", "ledgerlens.anomaly.created_count": 1},
    ]
    for span in [account, *rules]:
        assert span.parent is not None
        assert span.parent.span_id == root.context.span_id
    # The transaction pages and the balance are fetched inside the account span.
    inside_account = [
        span for span in clients if span.parent and span.parent.span_id == account.context.span_id
    ]
    assert len(inside_account) == 3


@pytest.mark.usefixtures("settings")
def test_each_demobank_request_carries_the_trace_id_of_the_server_span(
    otel: InMemoryTelemetry, store: Store
) -> None:
    seen: list[httpx.Request] = []

    response = client(store, requests_seen(seen, fake_demobank)).post("/api/sync")

    assert response.status_code == 200
    root = server_span(otel.finished_spans())
    expected = trace.format_trace_id(root.context.trace_id)
    assert len(seen) == 4
    for request in seen:
        version, trace_id, parent_id, flags = request.headers["traceparent"].split("-")
        assert (version, trace_id) == ("00", expected)
        assert int(flags, 16) & 1  # sampled
        assert len(parent_id) == 16


@pytest.mark.usefixtures("settings")
def test_a_failed_listing_marks_the_client_and_server_spans_with_the_error_kind(
    otel: InMemoryTelemetry, store: Store
) -> None:
    response = client(store, raising(httpx.ConnectError("refused"))).post("/api/sync")

    assert response.status_code == 502
    spans = otel.finished_spans()
    root = server_span(spans)
    [request] = [span for span in spans if span.kind is SpanKind.CLIENT]
    assert {span.context.trace_id for span in spans} == {root.context.trace_id}
    assert request.status.status_code is StatusCode.ERROR
    assert root.status.status_code is StatusCode.ERROR
    assert attributes(root)["ledgerlens.sync.error_kind"] == "connection"
    assert attributes(root)["http.response.status_code"] == 502
    assert by_name(spans, "sync account") == by_name(spans, "anomaly rule") == []


@pytest.mark.usefixtures("settings")
def test_a_failing_rule_marks_its_span_with_the_class_name_only(
    otel: InMemoryTelemetry, store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sync, "flag_large_expenses", failing_rule)

    response = client(store).post("/api/sync")

    assert response.status_code == 200
    duplicate, large = by_name(otel.finished_spans(), "anomaly rule")
    assert duplicate.status.status_code is StatusCode.UNSET
    assert large.status.status_code is StatusCode.ERROR
    assert large.status.description == "ValueError"
    assert large.events == ()
    assert attributes(large)["ledgerlens.anomaly.created_count"] == 0


@pytest.mark.usefixtures("settings")
def test_a_failed_account_marks_its_span(otel: InMemoryTelemetry, store: Store) -> None:
    def no_balance(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/balance"):
            return httpx.Response(503)
        return fake_demobank(request)

    client(store, no_balance).post("/api/sync")

    [account] = by_name(otel.finished_spans(), "sync account")
    assert account.status.status_code is StatusCode.ERROR
    assert account.status.description == "http_error"
    assert attributes(account)["ledgerlens.sync.status"] == "failed"


def test_redact_query_string_removes_query_strings_when_a_span_starts(
    otel: InMemoryTelemetry,
) -> None:
    tracer = trace.get_tracer("test")
    with tracer.start_as_current_span(
        "GET",
        attributes={
            "url.full": "http://demobank:8100/v1/x?cursor=abc&limit=5",
            "http.url": "http://h/p?q=secret",
            "http.target": "/p?q=secret",
            "url.query": "q=secret",
            "url.path": "/p",
        },
    ):
        pass

    [span] = otel.finished_spans()
    assert attributes(span) == {
        "url.full": "http://demobank:8100/v1/x",
        "http.url": "http://h/p",
        "http.target": "/p",
        "url.query": "",
        "url.path": "/p",
    }


# Metrics


def metric_attributes(otel: InMemoryTelemetry) -> dict[str, set[tuple[tuple[str, Any], ...]]]:
    found: dict[str, set[tuple[tuple[str, Any], ...]]] = {}
    for name, point_attributes, _ in otel.metric_points():
        found.setdefault(name, set()).add(tuple(sorted(point_attributes.items())))
    return found


def sums(otel: InMemoryTelemetry, name: str) -> dict[tuple[tuple[str, Any], ...], Any]:
    return {
        tuple(sorted(point_attributes.items())): getattr(point, "value", None)
        or getattr(point, "count", None)
        for metric, point_attributes, point in otel.metric_points()
        if metric == name
    }


@pytest.mark.usefixtures("settings")
def test_custom_metrics_carry_only_their_fixed_attributes(
    otel: InMemoryTelemetry, store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    sync_client = client(store)
    sync_client.post("/api/sync")
    sync_client.post("/api/sync")
    monkeypatch.setattr(sync, "flag_large_expenses", failing_rule)
    sync_client.post("/api/sync")
    client(store, raising(httpx.ConnectError("refused"))).post("/api/sync")

    found = metric_attributes(otel)
    outcomes = {"succeeded", "succeeded_with_errors", "failed"}
    assert found["ledgerlens.sync.runs"] <= {(("outcome", o),) for o in outcomes}
    assert found["ledgerlens.sync.runs"] >= {
        (("outcome", "succeeded"),),
        (("outcome", "succeeded_with_errors"),),
        (("outcome", "failed"),),
    }
    assert found["ledgerlens.sync.duration"] == found["ledgerlens.sync.runs"]
    assert found["ledgerlens.sync.transactions"] == {
        (("result", r),) for r in ("created", "skipped", "rejected")
    }
    assert found["ledgerlens.anomaly.flags"] == {
        (("rule", r),) for r in ("possible_duplicate", "large_expense")
    }


@pytest.mark.usefixtures("settings")
def test_a_second_sync_counts_a_run_and_no_new_transaction(
    otel: InMemoryTelemetry, store: Store
) -> None:
    sync_client = client(store)
    sync_client.post("/api/sync")
    before = sums(otel, "ledgerlens.sync.runs")
    created_before = sums(otel, "ledgerlens.sync.transactions")[(("result", "created"),)]

    sync_client.post("/api/sync")

    after = sums(otel, "ledgerlens.sync.runs")
    succeeded = (("outcome", "succeeded"),)
    assert after[succeeded] == before[succeeded] + 1
    assert sums(otel, "ledgerlens.sync.transactions")[(("result", "created"),)] == created_before


@pytest.mark.usefixtures("settings")
def test_http_metrics_use_the_route_template(otel: InMemoryTelemetry, store: Store) -> None:
    client(store).post("/api/sync")

    found = metric_attributes(otel)
    server = {dict(a).get("http.route") for a in found["http.server.request.duration"]}
    assert "/api/sync" in server
    assert all(route is None or "acc_" not in str(route) for route in server)
    assert "http.client.request.duration" in found


def account(status: str) -> AccountSyncResult:
    return AccountSyncResult(1, "a", status, 0, 0, 0, None, [])


@pytest.mark.parametrize(
    ("accounts", "rule_error", "expected"),
    [
        ([], None, "succeeded"),
        (["succeeded", "succeeded_with_errors"], None, "succeeded"),
        (["succeeded"], "ValueError", "succeeded_with_errors"),
        (["succeeded", "failed"], None, "succeeded_with_errors"),
        (["failed", "failed"], None, "failed"),
    ],
)
def test_run_outcome(accounts: list[str], rule_error: str | None, expected: str) -> None:
    result = SyncResult(
        [account(status) for status in accounts], [AnomalyRuleResult("x", 0, rule_error)]
    )

    assert sync.run_outcome(result) == expected


# Logs


@pytest.mark.usefixtures("settings")
def test_sync_finished_is_logged_inside_the_request_span(
    otel: InMemoryTelemetry, store: Store, capsys: pytest.CaptureFixture[str]
) -> None:
    capsys.readouterr()

    client(store).post("/api/sync")

    root = server_span(otel.finished_spans())
    trace_id = trace.format_trace_id(root.context.trace_id)
    [line] = [e for e in json_lines(capsys.readouterr().out) if e["message"] == "sync finished"]
    assert line["level"] == "INFO"
    assert line["logger"] == "ledgerlens.services.sync"
    assert line["trace_id"] == trace_id
    assert {k: line[k] for k in ("outcome", "accounts", "created_count", "flags")} == {
        "outcome": "succeeded",
        "accounts": 1,
        "created_count": 2,
        "flags": 2,
    }
    [exported] = [r for r in otel.log_records() if r.log_record.body == "sync finished"]
    assert exported.log_record.trace_id == root.context.trace_id
    assert exported.resource.attributes["service.name"] == "ledgerlens-backend"


@pytest.mark.usefixtures("settings")
def test_a_failed_listing_logs_one_warning_with_the_kind(
    otel: InMemoryTelemetry, store: Store, capsys: pytest.CaptureFixture[str]
) -> None:
    capsys.readouterr()

    client(store, raising(httpx.ConnectError("refused"))).post("/api/sync")

    lines = [e for e in json_lines(capsys.readouterr().out) if e["logger"].startswith("ledger")]
    assert [(e["level"], e["message"]) for e in lines] == [("WARNING", "sync failed: connection")]
    assert lines[0]["trace_id"] is not None


@pytest.mark.usefixtures("otel")
def test_every_line_is_one_json_object_with_the_ids(capsys: pytest.CaptureFixture[str]) -> None:
    create_app()
    capsys.readouterr()

    logging.getLogger("ledgerlens.test").warning("outside %s", "a span")
    with trace.get_tracer("test").start_as_current_span("x"):
        logging.getLogger("uvicorn.error").info("inside")

    outside, inside = json_lines(capsys.readouterr().out)
    assert set(outside) >= {"timestamp", "level", "logger", "message", "trace_id", "span_id"}
    assert outside["message"] == "outside a span"
    assert outside["level"] == "WARNING"
    assert outside["timestamp"].endswith("Z")
    assert len(outside["timestamp"]) == len("2026-11-13T10:15:02.123Z")
    assert outside["trace_id"] is None
    assert outside["span_id"] is None
    assert inside["logger"] == "uvicorn.error"
    assert re.fullmatch("[0-9a-f]{32}", inside["trace_id"])
    assert re.fullmatch("[0-9a-f]{16}", inside["span_id"])


def test_uvicorn_loggers_propagate_to_the_json_handler() -> None:
    create_app()
    create_app()

    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        assert logger.handlers == []
        assert logger.propagate is True
    root_handlers = logging.getLogger().handlers
    assert sum(isinstance(h.formatter, telemetry.JsonFormatter) for h in root_handlers) == 1


def test_the_access_line_has_no_query_string(capsys: pytest.CaptureFixture[str]) -> None:
    create_app()
    capsys.readouterr()

    logging.getLogger("uvicorn.access").info(
        '%s - "%s %s HTTP/%s" %d',
        "127.0.0.1:5000",
        "GET",
        "/api/transactions?q=SECRET",
        "1.1",
        200,
    )

    [line] = json_lines(capsys.readouterr().out)
    assert line["message"] == '127.0.0.1:5000 - "GET /api/transactions HTTP/1.1" 200'


def test_exceptions_are_written_as_their_class_name_only(
    capsys: pytest.CaptureFixture[str],
) -> None:
    create_app()
    capsys.readouterr()

    try:
        raise ValueError("SECRET-VALUE")
    except ValueError:
        logging.getLogger("ledgerlens.test").exception("it failed")

    output = capsys.readouterr().out
    [line] = json_lines(output)
    assert line["exception_type"] == "ValueError"
    assert "SECRET-VALUE" not in output


def test_the_sdks_own_records_are_not_exported(otel: InMemoryTelemetry) -> None:
    create_app()

    logging.getLogger("opentelemetry.exporter.otlp").warning("export failed")
    logging.getLogger("urllib3.connectionpool").warning("retrying")
    logging.getLogger("ledgerlens.test").warning("exported")

    assert [r.log_record.body for r in otel.log_records()] == ["exported"]


# Settings: OTEL_ENABLED


def settings_with(monkeypatch: pytest.MonkeyPatch, **variables: str) -> Settings:
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:pw@localhost/x")
    monkeypatch.setenv("DEMOBANK_API_KEY", "k")
    for name, value in variables.items():
        monkeypatch.setenv(name, value)
    get_settings.cache_clear()
    try:
        return get_settings()
    finally:
        get_settings.cache_clear()


def test_disabled_builds_no_exporter_and_starts_no_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("no exporter may be built")

    monkeypatch.setattr(telemetry, "install_providers", refuse)
    monkeypatch.setattr(telemetry, "OTLPSpanExporter", refuse)
    monkeypatch.setattr(telemetry, "OTLPMetricExporter", refuse)
    monkeypatch.setattr(telemetry, "OTLPLogExporter", refuse)

    telemetry.setup(settings_with(monkeypatch))
    with TestClient(create_app()) as started:
        started.get("/api/categories")

    assert not [t.name for t in threading.enumerate() if "otel" in t.name.lower()]


def test_enabled_exports_to_the_endpoint_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[Any, ...]] = []
    monkeypatch.setattr(telemetry, "install_providers", lambda *args: calls.append(args))

    telemetry.setup(
        settings_with(
            monkeypatch, OTEL_ENABLED="true", OTEL_EXPORTER_OTLP_ENDPOINT="http://collector:4318/"
        )
    )

    [(spans, reader, logs)] = calls
    assert spans._endpoint == "http://collector:4318/v1/traces"
    assert reader._exporter._endpoint == "http://collector:4318/v1/metrics"
    assert reader._export_interval_millis == 10_000
    assert logs._endpoint == "http://collector:4318/v1/logs"
    reader.shutdown()


def test_no_header_capture_variable_is_set() -> None:
    assert not [name for name in os.environ if name.startswith("OTEL_INSTRUMENTATION_HTTP_CAP")]


def test_export_failures_are_written_as_warnings(capsys: pytest.CaptureFixture[str]) -> None:
    create_app()
    capsys.readouterr()

    logging.getLogger("opentelemetry.exporter.otlp.proto.http").error("Failed to export")
    logging.getLogger("ledgerlens.test").error("a real error")

    exporter, own = json_lines(capsys.readouterr().out)
    assert (exporter["level"], own["level"]) == ("WARNING", "ERROR")
