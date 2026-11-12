"""Money and currency helpers: the one way LedgerLens handles EUR amounts.

The rule:

- Amounts are ``Decimal`` with exactly 2 decimals. Never ``float``.
- Rounding is ``ROUND_HALF_UP`` to 2 decimals (``0.005`` -> ``0.01``,
  ``-0.005`` -> ``-0.01``), and ``-0.00`` is normalised to ``0.00``.
- Rounding happens once, at the end of a calculation. ``Money`` never
  rounds: its constructor rejects extra precision. Intermediate values are
  plain ``Decimal`` at full precision, rounded with ``round_money``.
- EUR only.
- Range is -999,999,999,999.99 to 999,999,999,999.99 inclusive (the
  ``NUMERIC(14,2)`` limit).

All arithmetic runs in a local decimal context. The global context is never
read or changed.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import (
    ROUND_HALF_UP,
    Context,
    Decimal,
    DivisionByZero,
    InvalidOperation,
    Overflow,
    localcontext,
)
from typing import Final

CURRENCY: Final = "EUR"
MAX_AMOUNT: Final = Decimal("999999999999.99")
PRECISION: Final = 28

_CENT: Final = Decimal("0.01")
_ZERO: Final = Decimal("0.00")
_AMOUNT_PATTERN: Final = re.compile(r"-?[0-9]+(\.[0-9]+)?")
# Smallest magnitude that rounds half-up to a value outside the range.
_ROUNDS_OUT_OF_RANGE: Final = Decimal("999999999999.995")


class UnsupportedCurrencyError(ValueError):
    """The currency is not EUR, the only currency LedgerLens supports."""


def _context(precision: int = PRECISION) -> Context:
    """A fresh context, independent of whatever the global one holds."""
    return Context(
        prec=precision,
        rounding=ROUND_HALF_UP,
        traps=[InvalidOperation, DivisionByZero, Overflow],
    )


def _require_finite(value: Decimal) -> None:
    if not value.is_finite():
        raise ValueError(f"amount must be a finite number, got {value}")


def _to_amount(value: object) -> Decimal:
    """Validate a constructor value and return it with exactly 2 decimals."""
    if isinstance(value, bool):
        raise TypeError("amount must be a Decimal, int or str, not bool")
    if isinstance(value, Decimal):
        number = value
        _require_finite(number)
    elif isinstance(value, int):
        number = Decimal(value)
    elif isinstance(value, str):
        if _AMOUNT_PATTERN.fullmatch(value) is None:
            raise ValueError(f"malformed amount: {value!r}")
        number = Decimal(value)
    else:
        raise TypeError(f"amount must be a Decimal, int or str, not {type(value).__name__}")

    # Checked before any arithmetic: a huge exponent would overflow the context.
    if number.adjusted() > MAX_AMOUNT.adjusted():
        raise ValueError(f"amount out of range (max ±{MAX_AMOUNT})")
    with localcontext(_context()):
        if abs(number) > MAX_AMOUNT:
            raise ValueError(f"amount out of range (max ±{MAX_AMOUNT}): {value}")
        amount = number.quantize(_CENT)
        if amount != number:
            raise ValueError(f"amount has more than 2 decimals: {value}; use round_money")
        if amount == 0:
            return _ZERO
        return amount


@dataclass(frozen=True, init=False)
class Money:
    """An exact EUR amount with exactly 2 decimals."""

    amount: Decimal
    currency: str

    def __init__(self, amount: Decimal | int | str, currency: str = CURRENCY) -> None:
        if not isinstance(currency, str) or currency != CURRENCY:
            raise UnsupportedCurrencyError(f"unsupported currency: {currency!r}")
        object.__setattr__(self, "amount", _to_amount(amount))
        object.__setattr__(self, "currency", CURRENCY)

    def __str__(self) -> str:
        return format(self.amount, "f")

    def __add__(self, other: object) -> "Money":
        if not isinstance(other, Money):
            return NotImplemented
        with localcontext(_context()):
            return Money(self.amount + other.amount)

    def __sub__(self, other: object) -> "Money":
        if not isinstance(other, Money):
            return NotImplemented
        with localcontext(_context()):
            return Money(self.amount - other.amount)

    def __neg__(self) -> "Money":
        with localcontext(_context()):
            return Money(-self.amount)

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, Money):
            return NotImplemented
        return self.amount < other.amount

    def __le__(self, other: object) -> bool:
        if not isinstance(other, Money):
            return NotImplemented
        return self.amount <= other.amount

    def __gt__(self, other: object) -> bool:
        if not isinstance(other, Money):
            return NotImplemented
        return self.amount > other.amount

    def __ge__(self, other: object) -> bool:
        if not isinstance(other, Money):
            return NotImplemented
        return self.amount >= other.amount


def round_money(value: Decimal) -> Decimal:
    """Round to 2 decimals with ``ROUND_HALF_UP``; ``-0.00`` becomes ``0.00``.

    This is the one rounding step at the end of a calculation. There is no
    range limit, but a value too large to hold with 2 decimals at the module
    precision (28 digits) raises ``ValueError``.
    """
    if not isinstance(value, Decimal):
        raise TypeError(f"value must be a Decimal, not {type(value).__name__}")
    _require_finite(value)
    with localcontext(_context()):
        try:
            rounded = value.quantize(_CENT)
        except InvalidOperation:
            raise ValueError(f"value too large to round to 2 decimals: {value}") from None
        if rounded == 0:
            return _ZERO
        return rounded


def percent_of(part: Money, whole: Money) -> Decimal | None:
    """``part / whole x 100``, rounded once. ``None`` when ``whole`` is zero."""
    if not isinstance(part, Money) or not isinstance(whole, Money):
        raise TypeError("percent_of takes two Money values")
    if whole.amount == 0:
        return None
    with localcontext(_context()):
        raw = part.amount * 100 / whole.amount
    return round_money(raw)


def apply_percent(money: Money, pct: Decimal | int) -> Money:
    """``money x pct / 100``, rounded once.

    The intermediate value is exact: the precision is raised to fit the full
    product, so the only rounding is the final ``ROUND_HALF_UP`` step.
    """
    if not isinstance(money, Money):
        raise TypeError(f"money must be Money, not {type(money).__name__}")
    if isinstance(pct, bool) or not isinstance(pct, Decimal | int):
        raise TypeError(f"pct must be a Decimal or int, not {type(pct).__name__}")
    rate = Decimal(pct)
    _require_finite(rate)
    digits = len(money.amount.as_tuple().digits) + len(rate.as_tuple().digits)
    with localcontext(_context(max(PRECISION, digits))):
        try:
            raw = money.amount * rate / 100
        except Overflow:
            raise ValueError(f"result out of range (max ±{MAX_AMOUNT})") from None
        if abs(raw) >= _ROUNDS_OUT_OF_RANGE:
            raise ValueError(f"result out of range (max ±{MAX_AMOUNT}): {raw}")
        return Money(raw.quantize(_CENT))


def sum_money(items: Iterable[Money]) -> Money:
    """Add ``Money`` values exactly. An empty iterable gives ``Money("0.00")``.

    Only the total must be in range; a running total may leave it on the way.
    """
    total = _ZERO
    with localcontext(_context()):
        for item in items:
            if not isinstance(item, Money):
                raise TypeError(f"sum_money takes Money items, not {type(item).__name__}")
            total += item.amount
    return Money(total)
