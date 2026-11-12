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
