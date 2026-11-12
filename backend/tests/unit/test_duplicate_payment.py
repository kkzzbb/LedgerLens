"""The possible duplicate payment rule (#28)."""

import json
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from ledgerlens.domain.duplicate_payment import DuplicateFlag, Payment, find_possible_duplicates

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "demobank_seed42.json"
DAY = date(2026, 11, 12)
WINDOW = 3
TOLERANCE = Decimal("1")


def pay(
    id: int,
    days_later: int = 0,
    amount: str = "100.00",
    name: str | None = "Sparkvale Cleaning",
    direction: str = "debit",
) -> Payment:
    return Payment(id, DAY + timedelta(days=days_later), Decimal(amount), direction, name)


def flagged(*candidates: Payment) -> list[tuple[int, int]]:
    flags = find_possible_duplicates(candidates, [], WINDOW, TOLERANCE)
    return [(f.transaction_id, f.related_transaction_id) for f in flags]


def test_a_gap_of_3_days_is_flagged_and_4_is_not() -> None:
    assert flagged(pay(1), pay(2, days_later=3)) == [(2, 1)]
    assert flagged(pay(1), pay(2, days_later=4)) == []


def test_amounts_within_1_percent_of_the_larger_are_flagged() -> None:
    assert flagged(pay(1, amount="99.00"), pay(2, amount="100.00")) == [(2, 1)]
    assert flagged(pay(1, amount="98.99"), pay(2, amount="100.00")) == []


def test_a_different_counterparty_is_not_flagged() -> None:
    assert flagged(pay(1, name="Sparkvale Cleaning"), pay(2, name="Orchardine Wholesale")) == []


def test_a_credit_pair_is_not_flagged() -> None:
    assert flagged(pay(1, direction="credit"), pay(2, direction="credit")) == []


def test_a_same_day_pair_flags_the_higher_id() -> None:
    assert flagged(pay(7), pay(3)) == [(7, 3)]


def test_names_match_ignoring_case_and_spacing() -> None:
    assert flagged(pay(1, name="Sparkvale  Cleaning "), pay(2, name="sparkvale cleaning")) == [
        (2, 1)
    ]


def test_no_counterparty_name_is_not_flagged() -> None:
    assert flagged(pay(1, name=None), pay(2, name=None)) == []


def test_three_matching_debits_give_two_flags_each_on_the_closest_earlier() -> None:
    assert flagged(pay(1), pay(2, days_later=1), pay(3, days_later=2)) == [(2, 1), (3, 2)]


def test_only_candidates_are_flagged_and_the_reason_names_the_earlier_payment() -> None:
    flags = find_possible_duplicates(
        [pay(2, days_later=2, amount="455.00")], [pay(1, amount="455.00")], WINDOW, TOLERANCE
    )

    assert flags == [
        DuplicateFlag(
            2,
            1,
            "Possible duplicate of 455.00 paid to Sparkvale Cleaning on 2026-11-12 (2 days apart)",
        )
    ]


def seed42() -> list[Payment]:
    rows: list[dict[str, str]] = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return [
        Payment(
            int(row["transaction_id"].removeprefix("txn_")),
            date.fromisoformat(row["booking_date"]),
            Decimal(row["amount"]),
            row["direction"],
            row["counterparty_name"],
        )
        for row in rows
    ]


def test_seed42_history_gives_no_flag() -> None:
    history = seed42()[:-3]

    assert find_possible_duplicates(history, [], WINDOW, TOLERANCE) == []


def test_seed42_last_7_days_flag_only_the_planted_duplicate() -> None:
    payments = seed42()
    first_candidate_day = DAY - timedelta(days=6)
    candidates = [p for p in payments if p.booking_date >= first_candidate_day]
    history = [p for p in payments if p.booking_date < first_candidate_day]

    assert find_possible_duplicates(candidates, history, WINDOW, TOLERANCE) == [
        DuplicateFlag(
            240,
            239,
            "Possible duplicate of 455.00 paid to Sparkvale Cleaning on 2026-11-12 (0 days apart)",
        )
    ]
