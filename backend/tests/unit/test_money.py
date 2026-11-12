import ast
import dataclasses
import decimal
import operator
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from ledgerlens.domain import money as money_module
from ledgerlens.domain.money import Money, UnsupportedCurrencyError

MONEY_FILE = Path(money_module.__file__)
ALLOWED_IMPORTS = {"__future__", "collections.abc", "dataclasses", "decimal", "re", "typing"}


# Module and package


def test_module_imports_only_allowed_standard_library_modules() -> None:
    tree = ast.parse(MONEY_FILE.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "relative imports are not allowed"
            assert node.module is not None
            imported.add(node.module)
    assert imported, "the import check found no imports"
    assert imported <= ALLOWED_IMPORTS, f"disallowed imports: {imported - ALLOWED_IMPORTS}"


def test_module_docstring_states_the_rule() -> None:
    doc = money_module.__doc__
    assert doc is not None
    for phrase in (
        "Decimal",
        "exactly 2 decimals",
        "ROUND_HALF_UP",
        "once, at the end of a calculation",
        "EUR only",
        "999,999,999,999.99",
    ):
        assert phrase in doc


# The Money type


def test_money_is_a_frozen_dataclass_with_two_fields() -> None:
    assert dataclasses.is_dataclass(Money)
    fields = {field.name: field.type for field in dataclasses.fields(Money)}
    assert fields == {"amount": Decimal, "currency": str}
    m = Money("1.00")
    assert m.currency == "EUR"
    assert Money("1.00", "EUR") == m
    with pytest.raises(AttributeError):
        m.amount = Decimal("2.00")  # type: ignore[misc]
    with pytest.raises(AttributeError):
        m.currency = "USD"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (5, "5.00"),
        ("12.3", "12.30"),
        (Decimal("12.300"), "12.30"),
        (Decimal("12.30"), "12.30"),
        ("7", "7.00"),
        (-3, "-3.00"),
        (Decimal("1E+2"), "100.00"),
        (Decimal("0E-10"), "0.00"),
    ],
)
def test_amount_is_stored_with_exactly_two_decimals(
    value: Decimal | int | str, expected: str
) -> None:
    amount = Money(value).amount
    assert isinstance(amount, Decimal)
    assert amount == Decimal(expected)
    assert amount.as_tuple().exponent == -2
    assert str(amount) == expected


@pytest.mark.parametrize("value", ["1.234", Decimal("0.005"), Decimal("1.001"), "-0.001"])
def test_construction_never_rounds(value: Decimal | str) -> None:
    with pytest.raises(ValueError):
        Money(value)


@pytest.mark.parametrize(
    "value",
    [
        *["", "abc", "NaN", "Infinity", " 1.00", "1.00 ", "+1.00", "1e3", "1_000", "1,50"],
        *[".5", "5.", "1.00\n", "-", "--1"],
    ],
)
def test_malformed_string_raises_value_error(value: str) -> None:
    with pytest.raises(ValueError):
        Money(value)


@pytest.mark.parametrize("value", ["NaN", "sNaN", "Infinity", "-Infinity"])
def test_non_finite_decimal_raises_value_error(value: str) -> None:
    with pytest.raises(ValueError):
        Money(Decimal(value))


@pytest.mark.parametrize("value", [1.0, 0.1, True, False, None, [1], object()])
def test_float_bool_none_and_other_types_raise_type_error(value: object) -> None:
    with pytest.raises(TypeError):
        Money(value)  # type: ignore[arg-type]


def test_negative_amounts_are_allowed() -> None:
    assert Money("-12.50").amount == Decimal("-12.50")


@pytest.mark.parametrize("value", ["-0.00", "-0", Decimal("-0.00"), Decimal("-0")])
def test_negative_zero_is_normalised(value: Decimal | str) -> None:
    m = Money(value)
    assert m.amount == Decimal("0.00")
    assert not m.amount.is_signed()
    assert str(m) == "0.00"


@pytest.mark.parametrize("value", ["999999999999.99", "-999999999999.99"])
def test_range_limits_are_inclusive(value: str) -> None:
    m = Money(value)
    assert str(m) == value
    assert Money(str(m)) == m


@pytest.mark.parametrize(
    "value",
    ["1000000000000.00", "-1000000000000.00", 10**30, Decimal("1e30"), "1" + "0" * 40],
)
def test_out_of_range_raises_value_error(value: Decimal | int | str) -> None:
    with pytest.raises(ValueError):
        Money(value)


@pytest.mark.parametrize("currency", ["eur", "USD", "", None, " EUR", "EUR "])
def test_unsupported_currency_raises(currency: Any) -> None:
    with pytest.raises(UnsupportedCurrencyError):
        Money("1.00", currency)


def test_unsupported_currency_error_is_a_value_error() -> None:
    assert issubclass(UnsupportedCurrencyError, ValueError)


def test_equality_and_hash_are_by_value() -> None:
    assert Money("12.3") == Money("12.30")
    assert hash(Money("12.3")) == hash(Money("12.30"))
    assert Money("1.00") != Money("1.01")
    assert len({Money("12.3"), Money("12.30"), Money(Decimal("12.300"))}) == 1


def test_money_never_equals_a_bare_decimal() -> None:
    assert (Money("1.00") == Decimal("1.00")) is False
    assert (Decimal("1.00") == Money("1.00")) is False
    assert Money("1.00") != Decimal("1.00")


# Arithmetic and comparison


def test_addition_is_exact() -> None:
    assert Money("0.10") + Money("0.20") == Money("0.30")


def test_subtraction_is_exact() -> None:
    assert Money("1.00") - Money("2.50") == Money("-1.50")


def test_unary_minus() -> None:
    assert -Money("1.50") == Money("-1.50")
    assert -Money("-1.50") == Money("1.50")
    assert str(-Money("0.00")) == "0.00"


def test_subtraction_to_zero_is_not_negative_zero() -> None:
    assert str(Money("-1.00") + Money("1.00")) == "0.00"
    assert str(Money("1.00") - Money("1.00")) == "0.00"


@pytest.mark.parametrize("bare", [1, Decimal("1.00"), 1.0, "1.00"])
@pytest.mark.parametrize("op", [operator.add, operator.sub])
def test_arithmetic_with_a_bare_number_raises_type_error(
    op: Callable[[Any, Any], Any], bare: object
) -> None:
    with pytest.raises(TypeError):
        op(Money("1.00"), bare)
    with pytest.raises(TypeError):
        op(bare, Money("1.00"))


@pytest.mark.parametrize(
    ("op", "left", "right"),
    [
        (operator.add, "999999999999.99", "0.01"),
        (operator.add, "-999999999999.99", "-0.01"),
        (operator.sub, "-999999999999.99", "0.01"),
        (operator.sub, "999999999999.99", "-999999999999.99"),
    ],
)
def test_result_out_of_range_raises_value_error(
    op: Callable[[Money, Money], Money], left: str, right: str
) -> None:
    with pytest.raises(ValueError):
        op(Money(left), Money(right))


def test_comparisons_between_money() -> None:
    small, large = Money("1.00"), Money("2.00")
    assert small < large
    assert small <= large
    assert small <= Money("1.0")
    assert large > small
    assert large >= small
    assert large >= Money("2")
    assert not large < small
    assert Money("-5.00") < Money("0.00")


@pytest.mark.parametrize("bare", [1, Decimal("1.00"), 1.0, "1.00"])
@pytest.mark.parametrize("op", [operator.lt, operator.le, operator.gt, operator.ge])
def test_comparison_with_a_bare_number_raises_type_error(
    op: Callable[[Any, Any], Any], bare: object
) -> None:
    with pytest.raises(TypeError):
        op(Money("1.00"), bare)
    with pytest.raises(TypeError):
        op(bare, Money("1.00"))


@pytest.mark.parametrize("other", [2, Decimal("2"), 2.0, Money("2.00")])
@pytest.mark.parametrize("op", [operator.mul, operator.truediv, operator.floordiv])
def test_multiplication_and_division_are_not_defined(
    op: Callable[[Any, Any], Any], other: object
) -> None:
    with pytest.raises(TypeError):
        op(Money("1.00"), other)
    with pytest.raises(TypeError):
        op(other, Money("1.00"))


# Serialisation


@pytest.mark.parametrize("value", ["1234.50", "-0.01", "0.00", "999999999999.99"])
def test_str_is_the_plain_two_decimal_amount(value: str) -> None:
    assert str(Money(value)) == value


@pytest.mark.parametrize("value", ["1234.50", "-0.01", "0.00", "999999999999.99"])
def test_str_round_trips(value: str) -> None:
    m = Money(value)
    assert Money(str(m)) == m


def test_str_has_no_symbol_and_no_separator() -> None:
    assert str(Money(1234567)) == "1234567.00"
    assert str(Money(Decimal("1E+2"))) == "100.00"


# The global decimal context


def _context_state() -> tuple[int, str, list[str]]:
    ctx = decimal.getcontext()
    return ctx.prec, ctx.rounding, sorted(str(s) for s, on in ctx.traps.items() if on)


def test_global_context_is_never_changed() -> None:
    before = _context_state()
    a, b = Money("1.25"), Money("0.75")
    _ = a + b
    _ = a - b
    _ = -a
    _ = a < b, a <= b, a > b, a >= b
    _ = str(a), hash(a), a == b
    with pytest.raises(ValueError):
        Money("1.234")
    assert _context_state() == before
