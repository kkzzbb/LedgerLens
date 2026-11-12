"""The opaque paging cursor of `GET /v1/accounts/{account_id}/transactions` (#11).

A cursor is the URL-safe base64 of `{"b": "<booking_date>", "t": "<transaction_id>"}`:
the position of the last record a client has seen, never a row reference or an
offset. It is not signed and does not carry the account. Pure: no I/O.
"""

import base64
import binascii
import json
from dataclasses import dataclass
from datetime import date, datetime


class InvalidCursorError(ValueError):
    """The cursor is not base64, not the expected JSON shape, or holds a bad date."""


@dataclass(frozen=True)
class Position:
    booking_date: date
    transaction_id: str


def encode_cursor(position: Position) -> str:
    payload = {"b": position.booking_date.isoformat(), "t": position.transaction_id}
    raw = json.dumps(payload, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode("ascii")


def decode_cursor(cursor: str) -> Position:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii"))
        payload = json.loads(raw)
    except (UnicodeError, binascii.Error, ValueError) as error:
        raise InvalidCursorError(cursor) from error
    if not isinstance(payload, dict) or set(payload) != {"b", "t"}:
        raise InvalidCursorError(cursor)
    booking, transaction_id = payload["b"], payload["t"]
    if not isinstance(booking, str) or not isinstance(transaction_id, str) or not transaction_id:
        raise InvalidCursorError(cursor)
    try:
        booking_date = datetime.strptime(booking, "%Y-%m-%d").date()
    except ValueError as error:
        raise InvalidCursorError(cursor) from error
    if booking_date.isoformat() != booking:
        raise InvalidCursorError(cursor)
    return Position(booking_date=booking_date, transaction_id=transaction_id)
