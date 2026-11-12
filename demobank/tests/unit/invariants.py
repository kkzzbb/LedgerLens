"""Checkers for the balance and anomaly invariants of the generated history.

DemoBank imports nothing from `ledgerlens`, so the default thresholds are
copied here from `docs/accounting-rules.md` ("Anomaly rules") and from the
rule issues #28 (duplicate payment), #29 (unfamiliar counterparty), #30
(large expense), #31 (category increase) and #32 (evaluation window).

Each checker returns the list of violations (empty when the invariant holds),
so a failing test shows what broke.

A `Row` carries two amounts: `amount` is used where the row is evaluated
(the balance, the current month, the debit under test) and `baseline_amount`
where it is history for another row (a #30 or #31 baseline). For generated
data both are the real amount. For the worst case, debits have their range
maximum as `amount` and their minimum as `baseline_amount`, so every check
sees the current period at its highest and the baseline at its lowest.
"""

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from demobank.generator import EXPENSE_CATEGORIES, Dataset, Slot, Transaction

# docs/accounting-rules.md "Anomaly rules" and #28 to #32 (default values).
ANOMALY_EVALUATION_WINDOW_DAYS = 7  # #32
ANOMALY_DUPLICATE_WINDOW_DAYS = 3  # #28, inclusive
ANOMALY_DUPLICATE_AMOUNT_TOLERANCE_PERCENT = Decimal(1)  # #28, of the larger amount
ANOMALY_LARGE_EXPENSE_ABSOLUTE = Decimal("5000.00")  # #30, strictly greater
ANOMALY_LARGE_EXPENSE_MULTIPLIER = Decimal(3)  # #30, strictly greater
ANOMALY_MIN_HISTORY_COUNT = 3  # #30
ANOMALY_BASELINE_DAYS = 90  # #30
ANOMALY_CATEGORY_BASELINE_MONTHS = 3  # #31
ANOMALY_CATEGORY_INCREASE_PERCENT = Decimal(50)  # #31, strictly greater
ANOMALY_CATEGORY_MIN_INCREASE_AMOUNT = Decimal("200.00")  # #31, `>=` (stricter than ">")

ZERO = Decimal("0.00")


@dataclass(frozen=True)
class Row:
    booking_date: date
    counterparty: str
    category: str
    direction: str
    amount: Decimal
    baseline_amount: Decimal


def window_start(anchor_date: date) -> date:
    """The first day of the evaluation window (the 7 days ending on `anchor_date`)."""
    return anchor_date - timedelta(days=ANOMALY_EVALUATION_WINDOW_DAYS - 1)


def rows_from_dataset(dataset: Dataset, categories: dict[str, str]) -> list[Row]:
    """The generated transactions, in `(booking_date, transaction_id)` order."""

    def key(transaction: Transaction) -> tuple[date, str]:
        return transaction.booking_date, transaction.transaction_id

    return [
        Row(
            booking_date=t.booking_date,
            counterparty=t.counterparty_name,
            category=categories[t.counterparty_name],
            direction=t.direction,
            amount=t.amount,
            baseline_amount=t.amount,
        )
        for t in sorted(dataset.transactions, key=key)
    ]


def worst_case_rows(slots: Sequence[Slot], *, debits_first: bool) -> list[Row]:
    """The schedule with debits at their maximum (minimum as baseline) and
    credits at their minimum, optionally with the debits first within a day."""
    rows = []
    for slot in slots:
        low = Decimal(slot.min_cents).scaleb(-2)
        high = Decimal(slot.max_cents).scaleb(-2)
        rows.append(
            Row(
                booking_date=slot.booking_date,
                # Debits have exactly one counterparty. A credit's customer
                # does not matter to any check.
                counterparty=slot.counterparties[0].name,
                category=slot.category,
                direction=slot.direction,
                amount=high if slot.direction == "debit" else low,
                baseline_amount=low,
            )
        )
    if debits_first:
        # Stable: the schedule order is kept within the debits and the credits.
        rows.sort(key=lambda row: (row.booking_date, row.direction != "debit"))
    return rows


def lowest_balance(rows: Sequence[Row], opening_balance: Decimal) -> Decimal:
    """The lowest running balance, from the opening balance, in the order given."""
    balance = lowest = opening_balance
    for row in rows:
        balance += row.amount if row.direction == "credit" else -row.amount
        lowest = min(lowest, balance)
    return lowest


def balance_violations(rows: Sequence[Row], opening_balance: Decimal) -> list[str]:
    lowest = lowest_balance(rows, opening_balance)
    return [] if lowest >= ZERO else [f"the running balance goes down to {lowest}"]


def credits_violations(rows: Sequence[Row]) -> list[str]:
    credits = sum((r.amount for r in rows if r.direction == "credit"), ZERO)
    debits = sum((r.amount for r in rows if r.direction == "debit"), ZERO)
    return [] if credits > debits else [f"credits {credits} do not exceed debits {debits}"]


def absolute_limit_violations(rows: Sequence[Row]) -> list[str]:
    return [
        f"{r.booking_date} {r.counterparty}: {r.amount} > {ANOMALY_LARGE_EXPENSE_ABSOLUTE}"
        for r in rows
        if r.direction == "debit" and r.amount > ANOMALY_LARGE_EXPENSE_ABSOLUTE
    ]


def unfamiliar_counterparty_violations(rows: Sequence[Row], anchor_date: date) -> list[str]:
    """#29: every debit in the window has a counterparty booked before the window."""
    start = window_start(anchor_date)
    known = {r.counterparty for r in rows if r.booking_date < start}
    return [
        f"{r.booking_date} {r.counterparty}: no transaction before the window"
        for r in rows
        if r.direction == "debit"
        and start <= r.booking_date <= anchor_date
        and r.counterparty not in known
    ]


def duplicate_violations(rows: Sequence[Row], *, ignore_amounts: bool = False) -> list[str]:
    """#28: no two debits to one counterparty at most 3 days apart (inclusive)
    whose amounts differ by at most 1% of the larger one.

    `ignore_amounts` flags every pair within the window, whatever the amounts:
    the worst case, since the amounts drawn can be equal.
    """
    by_counterparty: dict[str, list[Row]] = defaultdict(list)
    for row in rows:
        if row.direction == "debit":
            by_counterparty[row.counterparty].append(row)
    found = []
    for counterparty, debits in by_counterparty.items():
        debits = sorted(debits, key=lambda row: row.booking_date)
        for index, earlier in enumerate(debits):
            for later in debits[index + 1 :]:
                gap = (later.booking_date - earlier.booking_date).days
                if gap > ANOMALY_DUPLICATE_WINDOW_DAYS:
                    break
                larger = max(earlier.amount, later.amount)
                tolerance = larger * ANOMALY_DUPLICATE_AMOUNT_TOLERANCE_PERCENT / 100
                if ignore_amounts or abs(earlier.amount - later.amount) <= tolerance:
                    found.append(f"{counterparty}: {earlier.booking_date} and {later.booking_date}")
    return found


def _baseline_mean(history: Sequence[Row]) -> Decimal | None:
    if len(history) < ANOMALY_MIN_HISTORY_COUNT:
        return None
    return sum((r.baseline_amount for r in history), ZERO) / len(history)


def large_expense_violations(rows: Sequence[Row], anchor_date: date) -> list[str]:
    """#30: no debit in the window is strictly above 3 times its baseline mean.

    The baseline is the mean of the counterparty's other debits booked in the
    90 days before it, when there are at least 3, else the mean of the other
    debits in its #25 category in those 90 days, when there are at least 3.
    Otherwise only the absolute limit applies (`absolute_limit_violations`).
    """
    start = window_start(anchor_date)
    debits = [r for r in rows if r.direction == "debit"]
    found = []
    for index, row in enumerate(debits):
        if not start <= row.booking_date <= anchor_date:
            continue
        recent = [
            other
            for other_index, other in enumerate(debits)
            if other_index != index
            and 0 <= (row.booking_date - other.booking_date).days <= ANOMALY_BASELINE_DAYS
        ]
        mean = _baseline_mean([r for r in recent if r.counterparty == row.counterparty])
        if mean is None:
            mean = _baseline_mean([r for r in recent if r.category == row.category])
        if mean is not None and row.amount > ANOMALY_LARGE_EXPENSE_MULTIPLIER * mean:
            found.append(f"{row.booking_date} {row.counterparty}: {row.amount} > 3 x {mean}")
    return found


def _previous_months(year: int, month: int, count: int) -> list[tuple[int, int]]:
    months = []
    for _ in range(count):
        year, month = (year, month - 1) if month > 1 else (year - 1, 12)
        months.append((year, month))
    return months


def window_months(anchor_date: date) -> list[tuple[int, int]]:
    """The calendar months the evaluation window touches: `anchor_date`'s month,
    and the previous one when the window crosses a month end."""
    start = window_start(anchor_date)
    months = [(start.year, start.month), (anchor_date.year, anchor_date.month)]
    return sorted(set(months))


def category_increase_violations(rows: Sequence[Row], anchor_date: date) -> list[str]:
    """#31: for each expense category and each month the window touches, the
    month-to-date total (up to and including `anchor_date`) is not both
    strictly above 1.5 x the mean of the 3 previous full months and at least
    200.00 above it."""
    factor = 1 + ANOMALY_CATEGORY_INCREASE_PERCENT / 100
    found = []
    for year, month in window_months(anchor_date):
        baseline_months = set(_previous_months(year, month, ANOMALY_CATEGORY_BASELINE_MONTHS))
        for category in EXPENSE_CATEGORIES:
            debits = [r for r in rows if r.direction == "debit" and r.category == category]
            current = sum(
                (
                    r.amount
                    for r in debits
                    if (r.booking_date.year, r.booking_date.month) == (year, month)
                    and r.booking_date <= anchor_date
                ),
                ZERO,
            )
            baseline_total = sum(
                (
                    r.baseline_amount
                    for r in debits
                    if (r.booking_date.year, r.booking_date.month) in baseline_months
                ),
                ZERO,
            )
            baseline = baseline_total / ANOMALY_CATEGORY_BASELINE_MONTHS
            if (
                current > baseline * factor
                and current - baseline >= ANOMALY_CATEGORY_MIN_INCREASE_AMOUNT
            ):
                found.append(
                    f"{category} {year}-{month:02d}: {current} against a baseline of {baseline}"
                )
    return found


def all_violations(
    rows: Sequence[Row],
    anchor_date: date,
    opening_balance: Decimal,
    *,
    ignore_duplicate_amounts: bool = False,
) -> dict[str, list[str]]:
    """Every invariant, by name. Each list is empty when the invariant holds."""
    return {
        "balance": balance_violations(rows, opening_balance),
        "credits": credits_violations(rows),
        "absolute limit": absolute_limit_violations(rows),
        "unfamiliar counterparty": unfamiliar_counterparty_violations(rows, anchor_date),
        "possible duplicate": duplicate_violations(rows, ignore_amounts=ignore_duplicate_amounts),
        "large expense": large_expense_violations(rows, anchor_date),
        "category increase": category_increase_violations(rows, anchor_date),
    }
