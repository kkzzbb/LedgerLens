"""DemoBank's traces and JSON logs (#122), with in-memory exporters and no database."""

import logging
import re
import threading
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from opentelemetry import trace
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.trace import SpanKind

from demobank import telemetry
from demobank.app import create_app
from demobank.config import Settings, get_settings
from tests.telemetry_support import InMemoryTelemetry, json_lines

API_KEY = "test-api-key"
TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
PARENT_ID = "00f067aa0ba902b7"


def no_database(settings: Settings) -> None:
    """Replaces the database step of the startup."""


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("DEMOBANK_API_KEY", API_KEY)
    monkeypatch.setenv("DEMOBANK_DATABASE_URL", "postgresql://u:pw@127.0.0.1:1/x")
    get_settings.cache_clear()
    with TestClient(create_app(database_step=no_database)) as started:
        yield started
    get_settings.cache_clear()


def server_spans(otel: InMemoryTelemetry) -> list[ReadableSpan]:
    return [span for span in otel.finished_spans() if span.kind is SpanKind.SERVER]


def test_a_traceparent_header_makes_the_server_span_its_child(
    otel: InMemoryTelemetry, client: TestClient
) -> None:
    response = client.get(
        "/v1/ping",
        headers={"X-API-Key": API_KEY, "traceparent": f"00-{TRACE_ID}-{PARENT_ID}-01"},
    )

    assert response.status_code == 200
    [span] = server_spans(otel)
    assert span.name == "GET /v1/ping"
    assert trace.format_trace_id(span.context.trace_id) == TRACE_ID
    assert span.parent is not None
    assert span.parent.is_remote
    assert trace.format_span_id(span.parent.span_id) == PARENT_ID
    assert span.resource.attributes["service.name"] == "demobank"


def test_server_spans_are_named_by_route_template(
    otel: InMemoryTelemetry, client: TestClient
) -> None:
    client.get("/v1/accounts/acc_operating_001/balance")  # 401: no key

    [span] = server_spans(otel)
    attributes: dict[str, Any] = dict(span.attributes or {})
    assert span.name == "GET /v1/accounts/{account_id}/balance"
    assert attributes["http.route"] == "/v1/accounts/{account_id}/balance"
    assert attributes["http.response.status_code"] == 401


def test_http_server_metrics_use_the_route_template(
    otel: InMemoryTelemetry, client: TestClient
) -> None:
    client.get("/v1/accounts/acc_operating_001/transactions")

    routes = {
        a.get("http.route")
        for name, a in otel.metric_attributes()
        if name == "http.server.request.duration"
    }
    assert "/v1/accounts/{account_id}/transactions" in routes
    assert all("acc_" not in str(route) for route in routes)


@pytest.mark.usefixtures("otel")
def test_every_line_is_one_json_object_with_the_ids(capsys: pytest.CaptureFixture[str]) -> None:
    create_app()
    capsys.readouterr()

    logging.getLogger("demobank.db.startup").info("outside")
    with trace.get_tracer("test").start_as_current_span("x"):
        logging.getLogger("uvicorn.error").warning("inside")

    outside, inside = json_lines(capsys.readouterr().out)
    assert set(outside) >= {"timestamp", "level", "logger", "message", "trace_id", "span_id"}
    assert (outside["level"], outside["logger"]) == ("INFO", "demobank.db.startup")
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z", outside["timestamp"])
    assert outside["trace_id"] is None
    assert outside["span_id"] is None
    assert re.fullmatch("[0-9a-f]{32}", inside["trace_id"])
    assert re.fullmatch("[0-9a-f]{16}", inside["span_id"])


def test_uvicorn_loggers_propagate_and_the_access_filter_is_attached_once() -> None:
    create_app()
    create_app()

    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        assert logger.handlers == []
        assert logger.propagate is True
    filters = logging.getLogger("uvicorn.access").filters
    assert sum(isinstance(item, telemetry.StripQueryString) for item in filters) == 1


def test_the_access_line_has_no_query_string(capsys: pytest.CaptureFixture[str]) -> None:
    create_app()
    capsys.readouterr()

    logging.getLogger("uvicorn.access").info(
        '%s - "%s %s HTTP/%s" %d',
        "172.18.0.5:40000",
        "GET",
        "/v1/accounts/acc_operating_001/transactions?cursor=SECRET&limit=100",
        "1.1",
        200,
    )

    [line] = json_lines(capsys.readouterr().out)
    assert line["message"] == (
        '172.18.0.5:40000 - "GET /v1/accounts/acc_operating_001/transactions HTTP/1.1" 200'
    )


def test_disabled_builds_no_exporter_and_starts_no_thread(
    monkeypatch: pytest.MonkeyPatch, client: TestClient
) -> None:
    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("no exporter may be built")

    monkeypatch.setattr(telemetry, "install_providers", refuse)
    monkeypatch.setattr(telemetry, "OTLPSpanExporter", refuse)

    telemetry.setup(get_settings())
    client.get("/health")

    assert not [t.name for t in threading.enumerate() if "otel" in t.name.lower()]


def test_enabled_exports_to_the_endpoint_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[Any, ...]] = []
    monkeypatch.setattr(telemetry, "install_providers", lambda *args: calls.append(args))
    monkeypatch.setenv("DEMOBANK_API_KEY", API_KEY)
    monkeypatch.setenv("DEMOBANK_DATABASE_URL", "postgresql://u:pw@127.0.0.1:1/x")
    monkeypatch.setenv("OTEL_ENABLED", "true")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel-lgtm:4318")
    get_settings.cache_clear()

    telemetry.setup(get_settings())
    get_settings.cache_clear()

    [(spans, reader, logs)] = calls
    assert spans._endpoint == "http://otel-lgtm:4318/v1/traces"
    assert reader._exporter._endpoint == "http://otel-lgtm:4318/v1/metrics"
    assert logs._endpoint == "http://otel-lgtm:4318/v1/logs"
    reader.shutdown()


def test_export_failures_are_written_as_warnings(capsys: pytest.CaptureFixture[str]) -> None:
    create_app()
    capsys.readouterr()

    logging.getLogger("opentelemetry.exporter.otlp.proto.http").error("Failed to export")

    [line] = json_lines(capsys.readouterr().out)
    assert line["level"] == "WARNING"
