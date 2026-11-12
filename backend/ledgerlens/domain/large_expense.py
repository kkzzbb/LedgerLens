"""The unusually large expense rule (#30, pure).

A candidate debit is flagged when its amount is above `absolute_limit`, or
above `multiplier` times the mean of its baseline (both strictly greater). The
baseline is the debits booked in the `baseline_days` calendar days before the
candidate's booking date: the counterparty's debits when there are at least
`min_history_count`, otherwise the same category's, otherwise none. A flag is
a potential issue for a person to review, never a finding of fraud or error
(`docs/accounting-rules.md`, Anomaly rules).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal, localcontext

# Enough digits to compare and average NUMERIC(14,2) amounts exactly.
_PRECISION = 100
_CENT = Decimal("0.01")


@dataclass(frozen=True)
class Expense:
    id: int
    booking_date: date
    # Always positive; `direction` carries the sign.
    amount: Decimal
    direction: str
    counterparty_name: str | None
    category: str | None


@dataclass(frozen=True)
class LargeExpenseFlag:
    transaction_id: int
    reason: str


def _counterparty_key(name: str | None) -> str:
    return " ".join((name or "").split()).casefold()


def _money(value: Decimal) -> Decimal:
    with localcontext(prec=_PRECISION):
        return value.quantize(_CENT, rounding=ROUND_HALF_UP)


def _plural(count: int, word: str) -> str:
    return f"{count} {word}" if count == 1 else f"{count} {word}s"


def find_large_expenses(
    candidates: Sequence[Expense],
    history: Sequence[Expense],
    absolute_limit: Decimal,
    multiplier: Decimal,
    min_history_count: int,
    baseline_days: int,
) -> list[LargeExpenseFlag]:
    """One flag per candidate debit that is unusually large.

    Only candidates are flagged; `history` only feeds baselines. Credits are
    never flagged and never count in a baseline.
    """
    debits: dict[int, Expense] = {}
    for expense in [*history, *candidates]:
        if expense.direction == "debit":
            debits.setdefault(expense.id, expense)

    flags: list[LargeExpenseFlag] = []
    for candidate in sorted(candidates, key=lambda e: (e.booking_date, e.id)):
        if candidate.direction != "debit":
            continue
        start = candidate.booking_date - timedelta(days=baseline_days)
        window = [e for e in debits.values() if start <= e.booking_date < candidate.booking_date]

        baseline: list[Expense] = []
        label = ""
        key = _counterparty_key(candidate.counterparty_name)
        if key:
            baseline = [e for e in window if _counterparty_key(e.counterparty_name) == key]
            label = " ".join((candidate.counterparty_name or "").split())
        if len(baseline) < min_history_count and candidate.category is not None:
            baseline = [e for e in window if e.category == candidate.category]
            label = f"{candidate.category} category"
        if len(baseline) < min_history_count:
            baseline = []

        parts: list[str] = []
        if candidate.amount > absolute_limit:
            parts.append(f"above the {_money(absolute_limit)} limit")
        if baseline:
            with localcontext(prec=_PRECISION):
                total = sum((e.amount for e in baseline), Decimal(0))
                count = len(baseline)
                if candidate.amount * count > multiplier * total:
                    parts.append(
                        f"above {multiplier} \u00d7 the {label} average of {_money(total / count)} "
                        f"({_plural(count, 'debit')} in {_plural(baseline_days, 'day')})"
                    )
        if parts:
            reason = f"{_money(candidate.amount)} is {' and '.join(parts)}"
            flags.append(LargeExpenseFlag(candidate.id, reason))
    return flags
