"""The balance and anomaly invariants of the generated history (#9).

For every seed and anchor date, the running balance never goes below 0,
credits exceed debits, and the ordinary history trips none of the
transaction rules #28 to #31 at their default thresholds. Each invariant is
tested three ways:

- range checks on the module's constants
- the worst case of the schedule for every anchor date from 2024-01-01 to
  2029-12-31: it covers every seed, because the dates do not depend on it
- a property test of `generate` over 200 seeds and anchor dates spread over
  2 years

The thresholds are in `tests/unit/invariants.py`, copied from
`docs/accounting-rules.md` and #28 to #32.
"""

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from itertools import pairwise

import pytest

from demobank.generator import (
    ANCHORED_RECEIPTS,
    COUNTERPARTIES,
    EXPENSE_CATEGORIES,
    HISTORY_DAYS,
    MONTHLY_PAYMENTS,
    OPENING_BALANCE_CENTS,
    RECEIPT_MIN_CENTS,
    cents_to_amount,
    generate,
    history_start,
    schedule,
)
from tests.unit.invariants import (
    ANOMALY_CATEGORY_INCREASE_PERCENT,
    ANOMALY_CATEGORY_MIN_INCREASE_AMOUNT,
    ANOMALY_DUPLICATE_WINDOW_DAYS,
    ANOMALY_LARGE_EXPENSE_ABSOLUTE,
    ANOMALY_LARGE_EXPENSE_MULTIPLIER,
    Row,
    all_violations,
    balance_violations,
    category_increase_violations,
    credits_violations,
    duplicate_violations,
    large_expense_violations,
    lowest_balance,
    rows_from_dataset,
    unfamiliar_counterparty_violations,
    window_months,
    worst_case_rows,
)

OPENING_BALANCE = cents_to_amount(OPENING_BALANCE_CENTS)
CATEGORIES = {counterparty.name: counterparty.category for counterparty in COUNTERPARTIES}

WORST_CASE_FIRST = date(2024, 1, 1)
WORST_CASE_LAST = date(2029, 12, 31)
# The lowest balance of the worst case found when the issue was groomed.
GROOMED_LOWEST_BALANCE = Decimal("18900.00")

# Feb has 28 days in a common year: the shortest gap across a month end.
SHORTEST_MONTH_DAYS = 28


def every_day(first: date, last: date) -> list[date]:
    return [first + timedelta(days=n) for n in range((last - first).days + 1)]


def payments_by_category() -> dict[str, list[tuple[int, int]]]:
    """Each expense category's monthly payments as (min cents, max cents)."""
    found: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for payment in MONTHLY_PAYMENTS:
        found[payment.counterparty.category].append((payment.min_cents, payment.max_cents))
    return found


def days_by_counterparty() -> dict[str, list[int]]:
    found: dict[str, list[int]] = defaultdict(list)
    for payment in MONTHLY_PAYMENTS:
        found[payment.counterparty.name].append(payment.day)
    return found


# Range checks on the constants


def test_every_debit_pattern_belongs_to_an_expense_category() -> None:
    assert set(payments_by_category()) == set(EXPENSE_CATEGORIES)


def test_every_monthly_day_exists_in_every_month() -> None:
    assert all(1 <= payment.day <= 28 for payment in MONTHLY_PAYMENTS)


def test_no_debit_can_exceed_the_absolute_limit() -> None:
    largest = max(cents_to_amount(payment.max_cents) for payment in MONTHLY_PAYMENTS)

    assert largest == Decimal("2800.00")
    assert largest <= ANOMALY_LARGE_EXPENSE_ABSOLUTE


@pytest.mark.parametrize(
    ("category", "smallest", "largest"),
    [
        ("inventory", "1700.00", "2400.00"),
        ("utilities", "120.00", "340.00"),
        ("software", "89.00", "189.00"),
        ("supplier_other", "240.00", "380.00"),
        ("rent", "2800.00", "2800.00"),
    ],
)
def test_largest_payment_is_at_most_3_times_the_smallest_in_each_category(
    category: str, smallest: str, largest: str
) -> None:
    # Then no payment can be strictly above 3 x a mean of payments of the same
    # vendor or category, whichever baseline #30 uses.
    ranges = payments_by_category()[category]
    low = cents_to_amount(min(low for low, _ in ranges))
    high = cents_to_amount(max(high for _, high in ranges))

    assert (low, high) == (Decimal(smallest), Decimal(largest))
    assert high <= ANOMALY_LARGE_EXPENSE_MULTIPLIER * low


@pytest.mark.parametrize(
    ("category", "smallest", "largest"),
    [
        ("inventory", "15300.00", "21600.00"),
        ("utilities", "420.00", "480.00"),
        ("software", "407.00", "407.00"),
        ("supplier_other", "620.00", "620.00"),
        ("rent", "2800.00", "2800.00"),
    ],
)
def test_largest_monthly_total_cannot_trip_the_category_increase_rule(
    category: str, smallest: str, largest: str
) -> None:
    ranges = payments_by_category()[category]
    low = cents_to_amount(sum(low for low, _ in ranges))
    high = cents_to_amount(sum(high for _, high in ranges))
    factor = 1 + ANOMALY_CATEGORY_INCREASE_PERCENT / 100

    assert (low, high) == (Decimal(smallest), Decimal(largest))
    assert high <= low * factor or high - low < ANOMALY_CATEGORY_MIN_INCREASE_AMOUNT


def test_same_counterparty_days_are_at_least_4_days_apart() -> None:
    for name, days in days_by_counterparty().items():
        days = sorted(days)
        within = [later - earlier for earlier, later in pairwise(days)]
        across = SHORTEST_MONTH_DAYS - days[-1] + days[0]
        assert all(gap > ANOMALY_DUPLICATE_WINDOW_DAYS for gap in [*within, across]), name


def test_smallest_credits_exceed_largest_debits_over_any_history() -> None:
    weekdays = []
    occurrences = []
    for anchor in every_day(date(2024, 1, 1), date(2031, 12, 31)):
        days = every_day(history_start(anchor), anchor)
        weekdays.append(sum(1 for day in days if day.weekday() < 5))
        occurrences.append(max(sum(1 for day in days if day.day == n) for n in range(1, 29)))
    monthly_debits = cents_to_amount(sum(payment.max_cents for payment in MONTHLY_PAYMENTS))

    assert min(weekdays) == 130
    assert max(occurrences) == 7
    assert monthly_debits == Decimal("25907.00")
    smallest_credits = min(weekdays) * cents_to_amount(RECEIPT_MIN_CENTS)
    largest_debits = max(occurrences) * monthly_debits
    assert (smallest_credits, largest_debits) == (Decimal("195000.00"), Decimal("181349.00"))
    assert smallest_credits > largest_debits


def test_anchored_receipts_are_credits_only() -> None:
    # They only add to the balance and the credits, so the invariants above
    # hold with or without them.
    assert all(receipt.amount_cents > 0 for receipt in ANCHORED_RECEIPTS)


# Worst case for every anchor date


def test_worst_case_for_every_anchor_date_from_2024_to_2029() -> None:
    lowest = []
    failures: dict[date, dict[str, list[str]]] = {}
    for anchor in every_day(WORST_CASE_FIRST, WORST_CASE_LAST):
        slots = schedule(anchor)
        rows = worst_case_rows(slots, debits_first=True)
        violations = all_violations(rows, anchor, OPENING_BALANCE, ignore_duplicate_amounts=True)
        in_order = worst_case_rows(slots, debits_first=False)
        violations["balance in schedule order"] = balance_violations(in_order, OPENING_BALANCE)
        if any(violations.values()):
            failures[anchor] = {name: found for name, found in violations.items() if found}
        lowest.append(lowest_balance(rows, OPENING_BALANCE))

    assert failures == {}
    assert len(lowest) == 2192
    assert min(lowest) == GROOMED_LOWEST_BALANCE


def test_worst_case_covers_a_window_crossing_a_month_end() -> None:
    # Anchors on days 1 to 6 put the window across a month end: both months
    # are checked by #31, the previous one as a whole month.
    assert window_months(date(2026, 7, 3)) == [(2026, 6), (2026, 7)]
    assert window_months(date(2026, 7, 7)) == [(2026, 7)]
    assert window_months(date(2027, 1, 1)) == [(2026, 12), (2027, 1)]


# Property test of `generate`


@pytest.mark.parametrize("seed", range(200))
def test_generated_history_satisfies_every_invariant(seed: int) -> None:
    anchor = date(2024, 1, 1) + timedelta(days=(29 * seed) % 731)
    dataset = generate(seed, anchor)

    rows = rows_from_dataset(dataset, CATEGORIES)
    violations = all_violations(rows, anchor, dataset.account.opening_balance)

    assert {name: found for name, found in violations.items() if found} == {}
    assert len(rows) == len(schedule(anchor))


def test_property_test_anchors_spread_over_2_years() -> None:
    anchors = {date(2024, 1, 1) + timedelta(days=(29 * seed) % 731) for seed in range(200)}

    assert len(anchors) == 200
    assert min(anchors).year == 2024
    assert max(anchors) >= date(2025, 12, 1)
    assert sum(1 for anchor in anchors if anchor.day <= 6) > 20  # window across a month end


# The checkers catch what they are meant to catch


def row(
    day: date,
    counterparty: str,
    amount: str,
    *,
    category: str = "utilities",
    direction: str = "debit",
    baseline: str | None = None,
) -> Row:
    return Row(
        booking_date=day,
        counterparty=counterparty,
        category=category,
        direction=direction,
        amount=Decimal(amount),
        baseline_amount=Decimal(baseline if baseline is not None else amount),
    )


ANCHOR = date(2026, 6, 30)


def test_balance_checker_catches_a_negative_balance() -> None:
    rows = [row(ANCHOR, "a", "100.00", direction="credit"), row(ANCHOR, "b", "150.00")]

    assert balance_violations(rows, Decimal("50.00")) == []  # down to exactly 0.00
    assert balance_violations(rows, Decimal("49.99")) != []


def test_credits_checker_needs_credits_strictly_above_debits() -> None:
    equal = [row(ANCHOR, "a", "100.00", direction="credit"), row(ANCHOR, "b", "100.00")]

    assert credits_violations(equal) != []
    assert credits_violations([*equal, row(ANCHOR, "a", "0.01", direction="credit")]) == []


def test_unfamiliar_checker_needs_a_booking_before_the_window() -> None:
    window_start = ANCHOR - timedelta(days=6)
    earlier = row(window_start - timedelta(days=1), "known", "10.00", direction="credit")
    in_window = row(window_start, "known", "10.00")

    assert unfamiliar_counterparty_violations([earlier, in_window], ANCHOR) == []
    assert unfamiliar_counterparty_violations([in_window], ANCHOR) != []
    # A first debit before the window is history, not evaluated.
    assert unfamiliar_counterparty_violations([earlier], ANCHOR) == []


def test_duplicate_checker_window_and_tolerance() -> None:
    first = row(ANCHOR - timedelta(days=3), "a", "100.00")

    assert duplicate_violations([first, row(ANCHOR, "a", "101.00")]) != []  # 1% of 101.00
    assert duplicate_violations([first, row(ANCHOR, "a", "101.02")]) == []
    assert duplicate_violations([first, row(ANCHOR, "b", "100.00")]) == []
    later = row(ANCHOR + timedelta(days=1), "a", "100.00")
    assert duplicate_violations([first, later]) == []  # 4 days apart
    assert duplicate_violations([first, row(ANCHOR, "a", "500.00")], ignore_amounts=True) != []


def test_large_expense_checker_uses_the_vendor_then_the_category_baseline() -> None:
    history = [row(ANCHOR - timedelta(days=d), "a", "100.00") for d in (30, 60, 90)]

    assert large_expense_violations([*history, row(ANCHOR, "a", "300.00")], ANCHOR) == []
    assert large_expense_violations([*history, row(ANCHOR, "a", "300.01")], ANCHOR) != []
    # Too little vendor history: the category baseline applies.
    assert large_expense_violations([*history, row(ANCHOR, "b", "300.01")], ANCHOR) != []
    # History older than 90 days does not count: only the absolute limit applies.
    old = [row(ANCHOR - timedelta(days=91), "a", "100.00"), *history[:2]]
    assert large_expense_violations([*old, row(ANCHOR, "a", "300.01")], ANCHOR) == []
    # The baseline uses each row's baseline amount.
    low = [row(r.booking_date, "a", "100.00", baseline="90.00") for r in history]
    assert large_expense_violations([*low, row(ANCHOR, "a", "280.00")], ANCHOR) != []


def test_category_checker_uses_both_thresholds_and_the_baseline_amounts() -> None:
    baseline = [row(date(2026, month, 8), "a", "400.00") for month in (3, 4, 5)]

    assert category_increase_violations([*baseline, row(ANCHOR, "a", "600.00")], ANCHOR) == []
    assert category_increase_violations([*baseline, row(ANCHOR, "a", "600.01")], ANCHOR) != []
    # +50% but less than 200.00 more: not flagged.
    small = [row(date(2026, month, 8), "a", "100.00") for month in (3, 4, 5)]
    assert category_increase_violations([*small, row(ANCHOR, "a", "299.99")], ANCHOR) == []
    # Exactly 200.00 more is flagged (#31's `>=`).
    assert category_increase_violations([*small, row(ANCHOR, "a", "300.00")], ANCHOR) != []
    # A baseline at its minimum lowers the threshold.
    low = [row(r.booking_date, "a", "400.00", baseline="380.00") for r in baseline]
    assert category_increase_violations([*low, row(ANCHOR, "a", "600.00")], ANCHOR) != []


def test_category_checker_covers_the_previous_month_when_the_window_crosses_it() -> None:
    anchor = date(2026, 7, 2)
    baseline = [row(date(2026, month, 8), "a", "400.00") for month in (3, 4, 5)]
    spike_in_june = row(date(2026, 6, 28), "a", "700.00")

    assert category_increase_violations([*baseline, spike_in_june], anchor) != []
    # With the window inside July, June is not evaluated.
    assert category_increase_violations([*baseline, spike_in_june], date(2026, 7, 7)) == []


def test_worst_case_rows_put_debits_first_and_use_the_range_ends() -> None:
    slots = schedule(date(2026, 6, 30))
    rows = worst_case_rows(slots, debits_first=True)
    first_day = [r for r in rows if r.booking_date == date(2026, 6, 1)]

    assert [r.direction for r in first_day] == ["debit", "credit"]
    inventory = next(r for r in rows if r.category == "inventory")
    assert (inventory.amount, inventory.baseline_amount) == (Decimal("2400.00"), Decimal("1700.00"))
    receipt = next(r for r in rows if r.direction == "credit")
    assert receipt.amount == Decimal("1500.00")
    assert len(rows) == len(slots)
    assert all(r.booking_date >= history_start(date(2026, 6, 30)) for r in rows)
    assert HISTORY_DAYS == 183
