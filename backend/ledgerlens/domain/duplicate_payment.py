"""The possible duplicate payment rule (#28, pure).

A candidate debit is flagged when an earlier debit to the same counterparty
was booked at most `window_days` before it, for an amount within
`tolerance_percent` of the larger of the two (both bounds inclusive). A flag is
a potential issue for a person to review, never a finding of fraud or error
(`docs/accounting-rules.md`, Anomaly rules).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, localcontext

# Enough digits to compare any NUMERIC(14,2) amount times any percentage exactly.
_PRECISION = 100
_CENT = Decimal("0.01")


@dataclass(frozen=True)
class Payment:
    id: int
    booking_date: date
    # Always positive; `direction` carries the sign.
    amount: Decimal
    direction: str
    counterparty_name: str | None


@dataclass(frozen=True)
class DuplicateFlag:
    transaction_id: int
    related_transaction_id: int
    reason: str


def _counterparty_key(name: str | None) -> str:
    return " ".join((name or "").split()).casefold()


def _within_tolerance(a: Decimal, b: Decimal, tolerance_percent: Decimal) -> bool:
    with localcontext(prec=_PRECISION):
        return abs(a - b) * 100 <= tolerance_percent * max(a, b)


def _reason(earlier: Payment, gap_days: int) -> str:
    amount = earlier.amount.quantize(_CENT, rounding=ROUND_HALF_UP)
    name = " ".join((earlier.counterparty_name or "").split())
    days = "day" if gap_days == 1 else "days"
    return (
        f"Possible duplicate of {amount} paid to {name} "
        f"on {earlier.booking_date.isoformat()} ({gap_days} {days} apart)"
    )


def find_possible_duplicates(
    candidates: Sequence[Payment],
    history: Sequence[Payment],
    window_days: int,
    tolerance_percent: Decimal,
) -> list[DuplicateFlag]:
    """One flag per candidate debit that may duplicate an earlier debit.

    "Earlier" means a lower `(booking_date, id)`. The related transaction is
    the closest earlier match. Only candidates are flagged; `history` only
    provides earlier matches. Credits and debits without a counterparty name
    are never flagged and never match.
    """
    by_counterparty: dict[str, list[Payment]] = {}
    seen: set[int] = set()
    for payment in [*history, *candidates]:
        key = _counterparty_key(payment.counterparty_name)
        if payment.direction != "debit" or not key or payment.id in seen:
            continue
        seen.add(payment.id)
        by_counterparty.setdefault(key, []).append(payment)

    flags: list[DuplicateFlag] = []
    for candidate in sorted(candidates, key=lambda p: (p.booking_date, p.id)):
        key = _counterparty_key(candidate.counterparty_name)
        if candidate.direction != "debit" or not key:
            continue
        own = (candidate.booking_date, candidate.id)
        matches = [
            earlier
            for earlier in by_counterparty[key]
            if (earlier.booking_date, earlier.id) < own
            and (candidate.booking_date - earlier.booking_date).days <= window_days
            and _within_tolerance(candidate.amount, earlier.amount, tolerance_percent)
        ]
        if not matches:
            continue
        closest = max(matches, key=lambda p: (p.booking_date, p.id))
        gap = (candidate.booking_date - closest.booking_date).days
        flags.append(DuplicateFlag(candidate.id, closest.id, _reason(closest, gap)))
    return flags
