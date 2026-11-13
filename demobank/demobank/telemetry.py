"""OpenTelemetry traces, metrics and logs, and JSON log lines on stdout (#122).

The pieces, in the order the application uses them:

- `instrument_app(app)`, from `create_app()`: JSON logging on stdout (with
  the query strings removed from uvicorn's access lines) and the FastAPI
  instrumentation. It reads no settings. Until providers are installed the
  instrumentation uses OpenTelemetry's no-op providers. DemoBank makes no
  outbound HTTP call, so there is no httpx instrumentation.
- `setup(settings)`, from the lifespan once the settings are valid: the
  psycopg instrumentation (before the first database connection) and, only
  when `OTEL_ENABLED` is true, the tracer, meter and logger providers that
  export over OTLP/HTTP to `OTEL_EXPORTER_OTLP_ENDPOINT`.
- `install_providers(...)`: the providers themselves. The tests call it once
  with in-memory exporters.

Every step is idempotent: `create_app()` and the lifespan may run several
times in one process (the tests do) without adding a second handler,
processor or exporter.

Privacy: no HTTP header is captured (the `X-API-Key` header included), no
body is recorded, `RedactQueryString`
removes query strings (the `cursor`) from spans before any exporter sees them, the psycopg
instrumentation keeps its defaults (SQL with placeholders, no parameters, no
commenter), and the OTLP log handler ignores the OpenTelemetry SDK's own
loggers so that an export failure is never itself exported.
"""

import json
import logging
import os
import sys
from datetime import UTC, datetime
from typing import Any, Final

from fastapi import FastAPI
from opentelemetry import metrics, trace
from opentelemetry._logs import set_logger_provider
from opentelemetry.context import Context
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.logging.handler import LoggingHandler
from opentelemetry.instrumentation.psycopg import PsycopgInstrumentor
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import (
    BatchLogRecordProcessor,
    LogRecordExporter,
    SimpleLogRecordProcessor,
)
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import MetricReader, PeriodicExportingMetricReader
from opentelemetry.sdk.resources import SERVICE_NAME as SERVICE_NAME_KEY
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import Span, SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor, SpanExporter

from demobank.config import Settings

# The `service.name` resource attribute. A constant, not a setting: the
# backend and DemoBank share one `.env`.
SERVICE_NAME: Final = "demobank"
# Metrics are exported every 10 seconds, so a sync shows up in Grafana quickly.
METRIC_EXPORT_INTERVAL_MILLIS: Final = 10_000
# Loggers whose records never go to the OTLP log handler: the SDK's own
# warnings about failed exports, and the HTTP library the exporter uses.
_NOT_EXPORTED_LOGGERS: Final = ("opentelemetry", "urllib3", "requests")
# Loggers kept at WARNING: they would log full request URLs at INFO.
_QUIET_LOGGERS: Final = ("httpx", "httpcore")
# Span attributes that may hold a full URL or a query string.
_URL_ATTRIBUTES: Final = ("url.full", "http.url", "http.target")
_QUERY_ATTRIBUTE: Final = "url.query"

_installed: dict[str, Any] = {}


# Logging


# `LogRecord` attributes that are not extra fields of a log call.
_STANDARD_RECORD_ATTRIBUTES: Final = frozenset(
    vars(logging.LogRecord("", 0, "", 0, "", None, None))
) | {"message", "asctime", "color_message", "taskName"}


def _hex_ids() -> tuple[str | None, str | None]:
    """The trace and span IDs of the current span, or `(None, None)` outside one."""
    context = trace.get_current_span().get_span_context()
    if not context.is_valid:
        return None, None
    return trace.format_trace_id(context.trace_id), trace.format_span_id(context.span_id)


class JsonFormatter(logging.Formatter):
    """One JSON object per record: timestamp, level, logger, message, IDs, extra fields.

    Only the formatted message and the extra fields whose values are plain
    numbers, strings, booleans or `None` are written. No exception text: a
    traceback may quote values.
    """

    def format(self, record: logging.LogRecord) -> str:
        trace_id, span_id = _hex_ids()
        timestamp = datetime.fromtimestamp(record.created, UTC)
        line: dict[str, Any] = {
            "timestamp": timestamp.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "trace_id": trace_id,
            "span_id": span_id,
        }
        if record.exc_info and record.exc_info[0] is not None:
            line["exception_type"] = record.exc_info[0].__name__
        for key, value in vars(record).items():
            if key in _STANDARD_RECORD_ATTRIBUTES or key in line:
                continue
            if value is None or isinstance(value, str | int | float | bool):
                line[key] = value
        return json.dumps(line, ensure_ascii=False)


class _StdoutHandler(logging.StreamHandler):  # type: ignore[type-arg]
    """Writes to the current `sys.stdout` (pytest replaces it per test)."""

    def emit(self, record: logging.LogRecord) -> None:
        self.stream = sys.stdout
        super().emit(record)


class _OtlpLogHandler(LoggingHandler):
    """The SDK handler without exception messages, stack traces or uvicorn's color copy.

    The exception class name (`exception.type`) is kept: a message or a
    traceback may quote values.
    """

    def _get_attributes(self, record: logging.LogRecord) -> tuple[dict[str, Any], str | None]:
        attributes, event_name = super()._get_attributes(record)
        for key in ("exception.message", "exception.stacktrace", "color_message"):
            attributes.pop(key, None)
        return attributes, event_name


class _NotExported(logging.Filter):
    """Keeps the OpenTelemetry SDK's and its HTTP client's own records out of OTLP."""

    def filter(self, record: logging.LogRecord) -> bool:
        return not record.name.startswith(_NOT_EXPORTED_LOGGERS)


class StripQueryString(logging.Filter):
    """Drops the query string (`cursor`, `limit`) from uvicorn access log records.

    Uvicorn's access record `args` are
    `(client_addr, method, full_path, http_version, status_code)`.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3 and isinstance(args[2], str):
            record.args = (*args[:2], args[2].split("?", 1)[0], *args[3:])
        return True


def configure_logging() -> None:
    """JSON lines on stdout for every logger, uvicorn's included. Idempotent.

    Uvicorn gives its loggers their own handlers and `propagate=False`; those
    handlers are removed and the records propagate to the root logger.
    """
    root = logging.getLogger()
    if not any(isinstance(handler, _StdoutHandler) for handler in root.handlers):
        handler = _StdoutHandler(sys.stdout)
        handler.setFormatter(JsonFormatter())
        root.addHandler(handler)
    if root.level == logging.NOTSET or root.level > logging.INFO:
        root.setLevel(logging.INFO)
    # httpx logs every request URL at INFO, query string (DemoBank cursor) included.
    for name in _QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        for existing in list(logger.handlers):
            logger.removeHandler(existing)
        logger.propagate = True
    access = logging.getLogger("uvicorn.access")
    if not any(isinstance(existing, StripQueryString) for existing in access.filters):
        access.addFilter(StripQueryString())
    logging.getLogger("demobank").setLevel(logging.INFO)


# Traces


def redact_query_string(span: trace.Span) -> None:
    """Cuts `url.full`, `http.url` and `http.target` at `?` and empties `url.query`."""
    attributes = getattr(span, "attributes", None) or {}
    for key in _URL_ATTRIBUTES:
        value = attributes.get(key)
        if isinstance(value, str) and "?" in value:
            span.set_attribute(key, value.split("?", 1)[0])
    if _QUERY_ATTRIBUTE in attributes:
        span.set_attribute(_QUERY_ATTRIBUTE, "")


class RedactQueryString(SpanProcessor):
    """Removes query strings from spans when they start, before any exporter runs.

    The ASGI instrumentation sets the server span's attributes again after
    the start, so `instrument_app` also redacts them in its request hook.
    """

    def on_start(self, span: Span, parent_context: Context | None = None) -> None:
        redact_query_string(span)


def _redact_server_span(span: trace.Span, scope: dict[str, Any]) -> None:
    """The FastAPI `server_request_hook`: runs once the request attributes are set."""
    if span.is_recording():
        redact_query_string(span)


# Instrumentation


def _use_stable_http_semconv() -> None:
    """Stable HTTP names (`http.server.request.duration`, `url.path`, `http.route`).

    Read by the instrumentation the first time it instruments anything.
    """
    os.environ.setdefault("OTEL_SEMCONV_STABILITY_OPT_IN", "http")


def instrument_app(app: FastAPI) -> None:
    """JSON logging, then the FastAPI instrumentation. Reads no settings."""
    configure_logging()
    _use_stable_http_semconv()
    # No header capture and no body hooks: only the default attributes, redacted.
    FastAPIInstrumentor.instrument_app(
        app, server_request_hook=_redact_server_span, exclude_spans=["receive", "send"]
    )


def instrument_database() -> None:
    """Traces psycopg queries: SQL with placeholders only, no parameters, no commenter."""
    _use_stable_http_semconv()
    instrumentor = PsycopgInstrumentor()
    if not instrumentor.is_instrumented_by_opentelemetry:
        instrumentor.instrument()


def install_providers(
    span_exporter: SpanExporter,
    metric_reader: MetricReader,
    log_exporter: LogRecordExporter,
    *,
    batch: bool = True,
) -> None:
    """Sets the global tracer, meter and logger providers, once per process.

    `batch=True` exports in background threads (the application); `False`
    exports synchronously (the tests, with in-memory exporters). A second
    call does nothing.
    """
    if _installed:
        return
    resource = Resource.create({SERVICE_NAME_KEY: SERVICE_NAME})

    tracer_provider = TracerProvider(resource=resource)
    # Registered first, so the exporter's processor sees the redacted span.
    tracer_provider.add_span_processor(RedactQueryString())
    tracer_provider.add_span_processor(
        BatchSpanProcessor(span_exporter) if batch else SimpleSpanProcessor(span_exporter)
    )
    trace.set_tracer_provider(tracer_provider)

    meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
    metrics.set_meter_provider(meter_provider)

    logger_provider = LoggerProvider(resource=resource)
    logger_provider.add_log_record_processor(
        BatchLogRecordProcessor(log_exporter) if batch else SimpleLogRecordProcessor(log_exporter)
    )
    set_logger_provider(logger_provider)
    otlp_handler = _OtlpLogHandler(logger_provider=logger_provider)
    otlp_handler.addFilter(_NotExported())
    logging.getLogger().addHandler(otlp_handler)

    _installed.update(
        tracer_provider=tracer_provider,
        meter_provider=meter_provider,
        logger_provider=logger_provider,
        log_handler=otlp_handler,
    )


def providers_installed() -> bool:
    """True once `install_providers` has run in this process."""
    return bool(_installed)


def _otlp_url(endpoint: str, signal: str) -> str:
    return f"{endpoint.rstrip('/')}/v1/{signal}"


def setup(settings: Settings) -> None:
    """The lifespan step, before the database step: logging, psycopg, OTLP if enabled.

    With `OTEL_ENABLED` false nothing is exported: no exporter is built, no
    connection is opened and no export thread starts.
    """
    configure_logging()
    instrument_database()
    if not settings.otel_enabled:
        return
    endpoint = settings.otel_exporter_otlp_endpoint
    install_providers(
        OTLPSpanExporter(endpoint=_otlp_url(endpoint, "traces")),
        PeriodicExportingMetricReader(
            OTLPMetricExporter(endpoint=_otlp_url(endpoint, "metrics")),
            export_interval_millis=METRIC_EXPORT_INTERVAL_MILLIS,
        ),
        OTLPLogExporter(endpoint=_otlp_url(endpoint, "logs")),
    )
