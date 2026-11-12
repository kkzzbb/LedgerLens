import copy
from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from ledgerlens.domain.normalization import (
    REQUIRED_FIELDS,
    NormalizedTransaction,
    Rejection,
    normalize,
    normalize_batch,
)


def _record(**changes: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "transaction_id": "tx-1",
        "account_id": "acc-1",
        "booking_date": "2026-11-12",
        "value_date": "2026-11-13",
        "amount": "12.50",
        "currency": "EUR",
        "direction": "debit",
        "counterparty_name": "Acme",
        "counterparty_reference": "REF-1",
        "description": "Invoice 42",
        "status": "booked",
    }
    record.update(changes)
    return record


def _without(field: str) -> dict[str, Any]:
    record = _record()
    del record[field]
    return record


def _accepted(record: dict[str, Any]) -> NormalizedTransaction:
    result = normalize(record)
    assert isinstance(result, NormalizedTransaction), result
    return result


def _rejected(record: dict[str, Any]) -> Rejection:
    result = normalize(record)
    assert isinstance(result, Rejection), result
    return result


def test_valid_record_maps_every_column() -> None:
    record = _record()
    raw = copy.deepcopy(record)
    assert normalize(record) == NormalizedTransaction(
        external_transaction_id="tx-1",
        external_account_id="acc-1",
        booking_date=date(2026, 11, 12),
        value_date=date(2026, 11, 13),
        amount=Decimal("12.50"),
        currency="EUR",
        direction="debit",
        counterparty_name="Acme",
        counterparty_reference="REF-1",
        description="Invoice 42",
        status="booked",
        source_metadata=raw,
    )
    assert record == raw


def test_dataclasses_are_frozen() -> None:
    result = _accepted(_record())
    with pytest.raises(AttributeError):
        result.amount = Decimal("1.00")  # type: ignore[misc]
    rejection = _rejected(_without("amount"))
    with pytest.raises(AttributeError):
        rejection.code = "x"  # type: ignore[misc]


@pytest.mark.parametrize("field", REQUIRED_FIELDS)
@pytest.mark.parametrize("kind", ["absent", "null", "blank"])
def test_missing_required_field(field: str, kind: str) -> None:
    record = (
        _without(field)
        if kind == "absent"
        else _record(**{field: None if kind == "null" else "  "})
    )
    rejection = _rejected(record)
    assert (rejection.field, rejection.code) == (field, "missing_field")


@pytest.mark.parametrize(
    "field",
    [f for f in REQUIRED_FIELDS if f != "amount"]
    + ["value_date", "counterparty_name", "counterparty_reference", "description"],
)
@pytest.mark.parametrize("value", [5, ["x"]])
def test_non_string_field_is_invalid_field(field: str, value: object) -> None:
    rejection = _rejected(_record(**{field: value}))
    assert (rejection.field, rejection.code) == (field, "invalid_field")


@pytest.mark.parametrize("currency", ["eur", "USD"])
def test_unsupported_currency(currency: str) -> None:
    rejection = _rejected(_record(currency=currency))
    assert (rejection.field, rejection.code) == ("currency", "unsupported_currency")


@pytest.mark.parametrize(
    "amount",
    [
        12.5,
        12,
        "1.234",
        "-5.00",
        "0.00",
        "abc",
        "NaN",
        "Infinity",
        "1E3",
        " 5.00",
        "1000000000000.00",
        "1" + "0" * 1000000,
    ],
)
def test_invalid_amount(amount: object) -> None:
    rejection = _rejected(_record(amount=amount))
    assert (rejection.field, rejection.code) == ("amount", "invalid_amount")


@pytest.mark.parametrize(
    ("amount", "expected"),
    [("999999999999.99", "999999999999.99"), ("0.01", "0.01"), ("12.5", "12.50"), ("7", "7.00")],
)
def test_valid_amount_has_two_decimals(amount: str, expected: str) -> None:
    result = _accepted(_record(amount=amount)).amount
    assert isinstance(result, Decimal)
    assert str(result) == expected


@pytest.mark.parametrize("direction", ["debit", "credit"])
def test_valid_direction(direction: str) -> None:
    assert _accepted(_record(direction=direction)).direction == direction


@pytest.mark.parametrize("direction", ["Debit", "in", "out"])
def test_invalid_direction(direction: str) -> None:
    rejection = _rejected(_record(direction=direction))
    assert (rejection.field, rejection.code) == ("direction", "invalid_direction")


@pytest.mark.parametrize("field", ["booking_date", "value_date"])
@pytest.mark.parametrize("value", ["2026-02-30", "20261112", "2026-11-12T00:00:00"])
def test_invalid_date(field: str, value: str) -> None:
    rejection = _rejected(_record(**{field: value}))
    assert (rejection.field, rejection.code) == (field, "invalid_date")


@pytest.mark.parametrize("record", [_without("value_date"), _record(value_date=None)])
def test_value_date_absent_or_null_gives_none(record: dict[str, Any]) -> None:
    assert _accepted(record).value_date is None


@pytest.mark.parametrize("field", ["counterparty_name", "counterparty_reference", "description"])
def test_optional_text_is_trimmed_and_empty_becomes_none(field: str) -> None:
    assert getattr(_accepted(_record(**{field: "  x y  "})), field) == "x y"
    for record in (
        _record(**{field: ""}),
        _record(**{field: "   "}),
        _record(**{field: None}),
        _without(field),
    ):
        assert getattr(_accepted(record), field) is None


def test_required_text_is_trimmed() -> None:
    result = _accepted(
        _record(
            transaction_id=" tx-1 ",
            account_id=" acc-1 ",
            currency=" EUR ",
            direction=" credit ",
            status=" booked ",
        )
    )
    assert (
        result.external_transaction_id,
        result.external_account_id,
        result.currency,
        result.direction,
        result.status,
    ) == ("tx-1", "acc-1", "EUR", "credit", "booked")


def test_rejection_external_id_is_trimmed_transaction_id() -> None:
    assert _rejected(_record(transaction_id=" tx-9 ", amount="abc")).external_id == "tx-9"


@pytest.mark.parametrize("transaction_id", [None, "   ", 42])
def test_rejection_external_id_none_without_usable_transaction_id(transaction_id: object) -> None:
    assert _rejected(_record(transaction_id=transaction_id)).external_id is None


def test_rejection_never_contains_the_raw_value() -> None:
    secret = "SECRET-VALUE-123"
    for field in ("amount", "currency", "direction", "booking_date"):
        rejection = _rejected(_record(**{field: secret}))
        assert secret not in repr(rejection)
        assert secret not in {rejection.external_id, rejection.field, rejection.code}


def test_first_problem_in_required_order_is_reported() -> None:
    record = _record(account_id=None, amount="abc", currency="USD", direction="x", status=None)
    assert _rejected(record).field == "account_id"
    record = _record(booking_date="bad", amount="abc", currency="USD")
    assert _rejected(record).field == "booking_date"
    record = _record(currency="USD", direction="x", description=5)
    assert _rejected(record).field == "currency"


def test_normalize_batch_splits_in_input_order() -> None:
    records = [
        _record(transaction_id="a"),
        _record(transaction_id="b", amount="0.00"),
        _record(transaction_id="c"),
        _record(transaction_id="d", currency="USD"),
        _record(transaction_id="e"),
    ]
    accepted, rejected = normalize_batch(records)
    assert [t.external_transaction_id for t in accepted] == ["a", "c", "e"]
    assert [r.external_id for r in rejected] == ["b", "d"]


def test_normalize_batch_empty() -> None:
    assert normalize_batch([]) == ([], [])
