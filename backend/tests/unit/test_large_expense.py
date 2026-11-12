"""The unusually large expense rule (#30)."""

import json
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from ledgerlens.domain.large_expense import Expense, LargeExpenseFlag, find_large_expenses

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "demobank_seed42.json"
DAY = date(2026, 11, 12)
LIMIT = Decimal("5000.00")
MULTIPLIER = Decimal("3")
MIN_HISTORY = 3
BASELINE_DAYS = 90


def exp(
    id: int,
    days_ago: int = 0,
    amount: str = "100.00",
    name: str | None = "Sparkvale Cleaning",
    category: str | None = "supplier_other",
    direction: str = "debit",
) -> Expense:
    return Expense(id, DAY - timedelta(days=days_ago), Decimal(amount), direction, name, category)


def find(candidates: list[Expense], history: list[Expense]) -> list[LargeExpenseFlag]:
    return find_large_expenses(candidates, history, LIMIT, MULTIPLIER, MIN_HISTORY, BASELINE_DAYS)


def flagged(candidate: Expense, *history: Expense) -> bool:
    return [f.transaction_id for f in find([candidate], list(history))] == [candidate.id]


def three_at_100(name: str | None = "Sparkvale Cleaning") -> list[Expense]:
    return [exp(10 + i, days_ago=1 + i, name=name) for i in range(3)]


def test_the_absolute_limit_is_strictly_greater() -> None:
    assert not flagged(exp(1, amount="5000.00", name=None, category=None))
    assert find([exp(1, amount="5000.01", name=None, category=None)], []) == [
        LargeExpenseFlag(1, "5000.01 is above the 5000.00 limit")
    ]


def test_the_counterparty_multiple_is_strictly_greater() -> None:
    assert not flagged(exp(1, amount="300.00"), *three_at_100())
    assert find([exp(1, amount="300.01")], three_at_100()) == [
        LargeExpenseFlag(
            1,
            "300.01 is above 3 \u00d7 the Sparkvale Cleaning average of 100.00 "
            "(3 debits in 90 days)",
        )
    ]


def test_with_two_counterparty_debits_the_category_mean_is_used() -> None:
    history = [
        exp(10, days_ago=1),
        exp(11, days_ago=2),
        exp(12, days_ago=3, amount="1000.00", name="Other Vendor"),
    ]
    # Counterparty mean would be 100.00; the category mean is 400.00.
    assert not flagged(exp(1, amount="1200.00"), *history)
    assert find([exp(1, amount="1200.01")], history) == [
        LargeExpenseFlag(
            1,
            "1200.01 is above 3 \u00d7 the supplier_other category average of 400.00 "
            "(3 debits in 90 days)",
        )
    ]


def test_with_fewer_than_3_in_both_only_the_limit_applies() -> None:
    history = three_at_100()[:2]

    assert not flagged(exp(1, amount="5000.00"), *history)
    assert flagged(exp(1, amount="5000.01"), *history)


def test_a_baseline_debit_on_day_minus_90_counts_and_on_minus_91_does_not() -> None:
    near = [exp(10, days_ago=1), exp(11, days_ago=2)]

    assert flagged(exp(1, amount="300.01"), *near, exp(12, days_ago=90))
    assert not flagged(exp(1, amount="300.01"), *near, exp(12, days_ago=91))


def test_a_same_day_debit_is_not_in_the_baseline() -> None:
    near = [exp(10, days_ago=1), exp(11, days_ago=2)]

    assert not flagged(exp(1, amount="300.01"), *near, exp(12))


def test_a_credit_is_neither_flagged_nor_in_a_baseline() -> None:
    assert not flagged(exp(1, amount="9000.00", direction="credit"))
    near = [exp(10, days_ago=1), exp(11, days_ago=2)]
    assert not flagged(exp(1, amount="300.01"), *near, exp(12, days_ago=3, direction="credit"))


def seed42() -> list[Expense]:
    rows: list[dict[str, str]] = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return [
        Expense(
            int(row["transaction_id"].removeprefix("txn_")),
            date.fromisoformat(row["booking_date"]),
            Decimal(row["amount"]),
            row["direction"],
            row["counterparty_name"],
            row["category"],
        )
        for row in rows
    ]


def test_seed42_history_gives_no_flag() -> None:
    assert find(seed42()[:-3], []) == []


def test_seed42_last_7_days_flag_only_the_planted_large_expense() -> None:
    expenses = seed42()
    first_candidate_day = DAY - timedelta(days=6)
    candidates = [e for e in expenses if e.booking_date >= first_candidate_day]
    history = [e for e in expenses if e.booking_date < first_candidate_day]

    assert {239, 240} <= {e.id for e in candidates}
    assert find(candidates, history) == [
        LargeExpenseFlag(
            241,
            "7850.00 is above the 5000.00 limit and above 3 \u00d7 the Orchardine Wholesale "
            "average of 1974.61 (8 debits in 90 days)",
        )
    ]
