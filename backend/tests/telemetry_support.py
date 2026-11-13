"""Telemetry helpers for the tests (#122): in-memory exporters and a fake DemoBank.

The global OpenTelemetry providers can be set only once per process, so
`in_memory_telemetry()` installs them once, with in-memory exporters, and
every telemetry test reads (and clears) the same exporters.

`MockedHTTPTransport` is a real `httpx.HTTPTransport`, the class the httpx
instrumentation wraps, whose connection pool hands each request to an
`httpx.MockTransport`. So the requests go through the instrumentation exactly
as in production, and never reach the network.
"""

import json
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import httpcore
import httpx
from opentelemetry.sdk._logs import ReadableLogRecord
from opentelemetry.sdk._logs.export import InMemoryLogRecordExporter
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from ledgerlens import telemetry


@dataclass(frozen=True)
class InMemoryTelemetry:
    spans: InMemorySpanExporter
    metrics: InMemoryMetricReader
    logs: InMemoryLogRecordExporter

    def clear(self) -> None:
        self.spans.clear()
        self.logs.clear()

    def finished_spans(self) -> list[ReadableSpan]:
        return list(self.spans.get_finished_spans())

    def log_records(self) -> list[ReadableLogRecord]:
        return list(self.logs.get_finished_logs())

    def metric_points(self) -> list[tuple[str, dict[str, Any], Any]]:
        """(metric name, attributes, data point) of every data point recorded so far."""
        data = self.metrics.get_metrics_data()
        points: list[tuple[str, dict[str, Any], Any]] = []
        if data is None:
            return points
        for resource_metrics in data.resource_metrics:
            for scope_metrics in resource_metrics.scope_metrics:
                for metric in scope_metrics.metrics:
                    for point in metric.data.data_points:
                        points.append((metric.name, dict(point.attributes or {}), point))
        return points


@lru_cache(maxsize=1)
def in_memory_telemetry() -> InMemoryTelemetry:
    """The process-wide providers, with in-memory exporters, installed on first use."""
    assert not telemetry.providers_installed(), "providers were installed before the tests"
    installed = InMemoryTelemetry(
        InMemorySpanExporter(),
        InMemoryMetricReader(),
        InMemoryLogRecordExporter(),  # type: ignore[no-untyped-call]
    )
    telemetry.install_providers(installed.spans, installed.metrics, installed.logs, batch=False)
    return installed


def span_text(span: ReadableSpan) -> str:
    """Name, attributes, events and status of a span, as one string."""
    return json.dumps(
        {
            "name": span.name,
            "attributes": dict(span.attributes or {}),
            "events": [
                {"name": event.name, "attributes": dict(event.attributes or {})}
                for event in span.events
            ],
            "status": [span.status.status_code.name, span.status.description],
            "resource": dict(span.resource.attributes),
        },
        default=str,
    )


def log_text(record: ReadableLogRecord) -> str:
    """Body and attributes of an exported log record, as one string."""
    log = record.log_record
    return json.dumps(
        {"body": log.body, "attributes": dict(log.attributes or {})},
        default=str,
    )


Handler = Callable[[httpx.Request], httpx.Response]


class _MockPool:
    """Stands in for httpcore's connection pool and calls a `MockTransport`."""

    def __init__(self, handler: Handler) -> None:
        self._mock = httpx.MockTransport(handler)

    def handle_request(self, request: httpcore.Request) -> httpcore.Response:
        url = request.url
        port = f":{url.port}" if url.port is not None else ""
        target = f"{url.scheme.decode()}://{url.host.decode()}{port}{url.target.decode()}"
        stream = request.stream
        body = b"".join(stream) if isinstance(stream, Iterable) else b""
        response = self._mock.handle_request(
            httpx.Request(
                request.method.decode(),
                target,
                headers=[(name, value) for name, value in request.headers],
                content=body,
            )
        )
        response.read()
        return httpcore.Response(
            response.status_code, headers=response.headers.raw, content=response.content
        )

    def close(self) -> None:
        return None


class MockedHTTPTransport(httpx.HTTPTransport):
    """A real `HTTPTransport` whose requests are answered by `handler`."""

    def __init__(self, handler: Handler) -> None:
        super().__init__()
        self._pool = _MockPool(handler)  # type: ignore[assignment]


def raising(error: Exception) -> Handler:
    """A handler that raises `error` (e.g. `httpx.ConnectError`) for every request."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise error

    return handler


def requests_seen(log: list[httpx.Request], handler: Handler) -> Handler:
    """`handler`, recording every request in `log`."""

    def recording(request: httpx.Request) -> httpx.Response:
        log.append(request)
        return handler(request)

    return recording


def json_lines(text: str) -> Iterator[dict[str, Any]]:
    """Every line of captured stdout, decoded as JSON (each must be one object)."""
    for line in text.splitlines():
        if line.strip():
            decoded = json.loads(line)
            assert isinstance(decoded, dict), line
            yield decoded


# A fake DemoBank whose records hold sentinel values: none may reach telemetry.

SENTINEL_API_KEY = "sentinel-api-key"
SENTINEL_DESCRIPTION = "SENTINEL-DESCRIPTION"
SENTINEL_COUNTERPARTY = "SENTINEL-COUNTERPARTY"
SENTINEL_REFERENCE = "SENTINEL-REFERENCE"
SENTINEL_IBAN = "NL91SENT0417164300"
SENTINEL_AMOUNT = "98765.43"
SENTINEL_CURSOR = "SENTINEL-CURSOR"
SENTINELS = (
    SENTINEL_API_KEY,
    SENTINEL_DESCRIPTION,
    SENTINEL_COUNTERPARTY,
    SENTINEL_REFERENCE,
    SENTINEL_IBAN,
    SENTINEL_AMOUNT,
    SENTINEL_CURSOR,
)
ACCOUNT_ID = "acc_operating_001"
DEMOBANK_URL = "http://demobank:8100"


def _transaction(transaction_id: str) -> dict[str, Any]:
    return {
        "transaction_id": transaction_id,
        "account_id": ACCOUNT_ID,
        "booking_date": "2026-11-10",
        "value_date": "2026-11-10",
        "amount": SENTINEL_AMOUNT,
        "currency": "EUR",
        "direction": "debit",
        "counterparty_name": SENTINEL_COUNTERPARTY,
        "counterparty_reference": SENTINEL_REFERENCE,
        "counterparty_account": SENTINEL_IBAN,
        "description": SENTINEL_DESCRIPTION,
        "status": "booked",
    }


def fake_demobank(request: httpx.Request) -> httpx.Response:
    """One account, two transaction pages (the second after `SENTINEL_CURSOR`), a balance."""
    if request.headers.get("X-API-Key") != SENTINEL_API_KEY:
        return httpx.Response(401, json={"error": "unauthorized"})
    path = request.url.path
    if path == "/v1/accounts":
        return httpx.Response(
            200,
            json=[
                {
                    "account_id": ACCOUNT_ID,
                    "display_name": "Operating",
                    "currency": "EUR",
                    "iban": SENTINEL_IBAN,
                }
            ],
        )
    if path == f"/v1/accounts/{ACCOUNT_ID}/balance":
        return httpx.Response(
            200,
            json={
                "account_id": ACCOUNT_ID,
                "balance": SENTINEL_AMOUNT,
                "currency": "EUR",
                "as_of": "2026-11-12T09:59:00Z",
            },
        )
    if path == f"/v1/accounts/{ACCOUNT_ID}/transactions":
        if request.url.params.get("cursor") == SENTINEL_CURSOR:
            page = {"transactions": [_transaction("t-2")], "next_cursor": "c-2", "has_more": False}
        else:
            page = {
                "transactions": [_transaction("t-1")],
                "next_cursor": SENTINEL_CURSOR,
                "has_more": True,
            }
        return httpx.Response(200, json=page)
    return httpx.Response(404, json={"error": "not_found"})
