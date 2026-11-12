"""Turn raw DemoBank transaction records into validated transactions.

``normalize`` returns a ``NormalizedTransaction`` ready to insert, or a
``Rejection`` naming the first failing field (in the order of
``REQUIRED_FIELDS``, then the optional fields). It never raises for a record
that is a ``dict``, so one bad record never breaks a batch.

A ``Rejection`` never holds a raw field value: it may be shown to users.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Final

from ledgerlens.domain.money import CURRENCY, Money

REQUIRED_FIELDS: Final = (
    "transaction_id",
    "account_id",
    "booking_date",
    "amount",
    "currency",
    "direction",
    "status",
)
DIRECTIONS: Final = frozenset({"debit", "credit"})

_DATE_PATTERN: Final = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


@dataclass(frozen=True)
class NormalizedTransaction:
    external_transaction_id: str
    external_account_id: str
    booking_date: date
    value_date: date | None
    amount: Decimal
    currency: str
    direction: str
    counterparty_name: str | None
    counterparty_reference: str | None
    description: str | None
    status: str
    source_metadata: dict[str, Any]


@dataclass(frozen=True)
class Rejection:
    external_id: str | None
    field: str
    code: str


class _Invalid(Exception):
    def __init__(self, field: str, code: str) -> None:
        self.field = field
        self.code = code


def _optional_text(record: dict[str, Any], field: str) -> str | None:
    value = record.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise _Invalid(field, "invalid_field")
    return value.strip() or None


def _required_text(record: dict[str, Any], field: str) -> str:
    value = _optional_text(record, field)
    if value is None:
        raise _Invalid(field, "missing_field")
    return value


def _parse_date(value: str, field: str) -> date:
    if _DATE_PATTERN.fullmatch(value) is None:
        raise _Invalid(field, "invalid_date")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise _Invalid(field, "invalid_date") from None


def _required_date(record: dict[str, Any], field: str) -> date:
    _required_text(record, field)
    return _parse_date(record[field], field)


def _optional_date(record: dict[str, Any], field: str) -> date | None:
    value = record.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise _Invalid(field, "invalid_field")
    return _parse_date(value, field)


def _amount(record: dict[str, Any]) -> Decimal:
    value = record.get("amount")
    if value is None or (isinstance(value, str) and not value.strip()):
        raise _Invalid("amount", "missing_field")
    if not isinstance(value, str):
        raise _Invalid("amount", "invalid_amount")
    try:
        amount = Money(value).amount
    except ValueError:
        raise _Invalid("amount", "invalid_amount") from None
    if amount <= 0:
        raise _Invalid("amount", "invalid_amount")
    return amount


def _external_id(record: dict[str, Any]) -> str | None:
    value = record.get("transaction_id")
    if isinstance(value, str):
        return value.strip() or None
    return None


def _normalize(record: dict[str, Any]) -> NormalizedTransaction:
    transaction_id = _required_text(record, "transaction_id")
    account_id = _required_text(record, "account_id")
    booking_date = _required_date(record, "booking_date")
    amount = _amount(record)
    currency = _required_text(record, "currency")
    if currency != CURRENCY:
        raise _Invalid("currency", "unsupported_currency")
    direction = _required_text(record, "direction")
    if direction not in DIRECTIONS:
        raise _Invalid("direction", "invalid_direction")
    status = _required_text(record, "status")
    return NormalizedTransaction(
        external_transaction_id=transaction_id,
        external_account_id=account_id,
        booking_date=booking_date,
        value_date=_optional_date(record, "value_date"),
        amount=amount,
        currency=currency,
        direction=direction,
        counterparty_name=_optional_text(record, "counterparty_name"),
        counterparty_reference=_optional_text(record, "counterparty_reference"),
        description=_optional_text(record, "description"),
        status=status,
        source_metadata=record,
    )


def normalize(record: dict[str, Any]) -> NormalizedTransaction | Rejection:
    """Validate one raw record; see the module docstring."""
    try:
        return _normalize(record)
    except _Invalid as invalid:
        return Rejection(external_id=_external_id(record), field=invalid.field, code=invalid.code)


def normalize_batch(
    records: Iterable[dict[str, Any]],
) -> tuple[list[NormalizedTransaction], list[Rejection]]:
    """Split records into accepted and rejected, each in input order."""
    accepted: list[NormalizedTransaction] = []
    rejected: list[Rejection] = []
    for record in records:
        result = normalize(record)
        if isinstance(result, Rejection):
            rejected.append(result)
        else:
            accepted.append(result)
    return accepted, rejected
