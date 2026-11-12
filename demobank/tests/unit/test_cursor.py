"""The paging cursor of #11: round trip and every way it can be invalid."""

import base64
from datetime import date

import pytest

from demobank.api.cursor import InvalidCursorError, Position, decode_cursor, encode_cursor


def b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode()


def test_round_trip_and_format() -> None:
    position = Position(date(2026, 6, 30), "txn_000123")
    cursor = encode_cursor(position)
    assert base64.urlsafe_b64decode(cursor) == b'{"b":"2026-06-30","t":"txn_000123"}'
    assert decode_cursor(cursor) == position


@pytest.mark.parametrize(
    "cursor",
    [
        "not base64!",
        "abc",
        b64("not json"),
        b64("[]"),
        b64('{"b": "2026-06-30"}'),
        b64('{"b": "2026-06-30", "t": 5}'),
        b64('{"b": "2026-06-30", "t": "txn_1", "x": 1}'),
        b64('{"b": "2026-02-30", "t": "txn_1"}'),
        b64('{"b": "20260630", "t": "txn_1"}'),
        b64('{"b": null, "t": "txn_1"}'),
    ],
)
def test_invalid_cursors_are_rejected(cursor: str) -> None:
    with pytest.raises(InvalidCursorError):
        decode_cursor(cursor)
