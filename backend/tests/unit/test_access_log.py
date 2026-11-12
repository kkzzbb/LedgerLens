"""The access log filter drops query strings, which may hold `q` (#23)."""

import logging

from ledgerlens.api.app import StripQueryString, create_app


def test_query_string_is_removed_from_an_access_record() -> None:
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:5000", "GET", "/api/transactions?limit=5&q=ernho", "1.1", 200),
        None,
    )

    assert StripQueryString().filter(record) is True
    message = record.getMessage()
    assert message == '127.0.0.1:5000 - "GET /api/transactions HTTP/1.1" 200'
    assert "ernho" not in message


def test_create_app_attaches_the_filter_once() -> None:
    create_app()
    create_app()
    filters = logging.getLogger("uvicorn.access").filters
    assert sum(isinstance(item, StripQueryString) for item in filters) == 1
