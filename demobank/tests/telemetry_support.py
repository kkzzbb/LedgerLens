"""In-memory telemetry for the tests (#122).

The global OpenTelemetry providers can be set only once per process, so
`in_memory_telemetry()` installs them once, with in-memory exporters, and
every telemetry test reads (and clears) the same exporters.
"""

import json
from collections.abc import Iterator
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from opentelemetry.sdk._logs import ReadableLogRecord
from opentelemetry.sdk._logs.export import InMemoryLogRecordExporter
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from demobank import telemetry


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

    def metric_attributes(self) -> list[tuple[str, dict[str, Any]]]:
        """(metric name, attributes) of every data point recorded so far."""
        data = self.metrics.get_metrics_data()
        found: list[tuple[str, dict[str, Any]]] = []
        if data is None:
            return found
        for resource_metrics in data.resource_metrics:
            for scope_metrics in resource_metrics.scope_metrics:
                for metric in scope_metrics.metrics:
                    for point in metric.data.data_points:
                        found.append((metric.name, dict(point.attributes or {})))
        return found


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
        },
        default=str,
    )


def log_text(record: ReadableLogRecord) -> str:
    """Body and attributes of an exported log record, as one string."""
    log = record.log_record
    return json.dumps({"body": log.body, "attributes": dict(log.attributes or {})}, default=str)


def json_lines(text: str) -> Iterator[dict[str, Any]]:
    """Every line of captured stdout, decoded as JSON (each must be one object)."""
    for line in text.splitlines():
        if line.strip():
            decoded = json.loads(line)
            assert isinstance(decoded, dict), line
            yield decoded
