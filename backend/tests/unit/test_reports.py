"""The month range and zero-filled report rows (`domain/reports.py`, #43)."""

from datetime import date
from decimal import Decimal

import pytest

from ledgerlens.domain.reports import (
    MonthRangeError,
    expense_figures,
    month_range,
    monthly_figures,
)


def test_range_spans_first_day_to_last_day() -> None:
    period = month_range("2026-11", "2027-02")
    assert period.months == ("2026-11", "2026-12", "2027-01", "2027-02")
    assert period.first_day == date(2026, 11, 1)
    assert period.last_day == date(2027, 2, 28)


def test_leap_february_ends_on_the_29th() -> None:
    assert month_range("2028-02", "2028-02").last_day == date(2028, 2, 29)


def test_same_month_is_one_month() -> None:
    assert month_range("2026-09", "2026-09").months == ("2026-09",)


def test_exactly_24_months_is_accepted() -> None:
    assert len(month_range("2025-01", "2026-12").months) == 24


@pytest.mark.parametrize(
    ("first", "last"),
    [
        ("2026-13", "2026-13"),
        ("2026-9", "2026-10"),
        ("abc", "2026-10"),
        ("2026-10", "2026-00"),
        ("2026-11", "2026-10"),
        ("2025-01", "2027-01"),
    ],
)
def test_invalid_range(first: str, last: str) -> None:
    with pytest.raises(MonthRangeError):
        month_range(first, last)


def test_monthly_fills_zero_and_nets_unrounded_sums() -> None:
    rows = monthly_figures(
        ("2026-09", "2026-10"),
        {"2026-09": Decimal("10.005")},
        {"2026-09": Decimal("20.004")},
    )
    assert [(r.month, str(r.money_in), str(r.money_out), str(r.net)) for r in rows] == [
        ("2026-09", "10.01", "20.00", "-10.00"),
        ("2026-10", "0.00", "0.00", "0.00"),
    ]


def test_expenses_fill_every_category_and_month_in_order() -> None:
    rows = expense_figures(
        ("2026-09", "2026-10"),
        {("rent", "2026-09"): Decimal("0.004"), ("rent", "2026-10"): Decimal("0.004")},
    )
    assert [r.key for r in rows] == [
        "rent",
        "software",
        "utilities",
        "inventory",
        "supplier_other",
        "other",
    ]
    assert rows[0].name == "Rent"
    assert str(rows[0].total) == "0.01"
    assert [str(m.amount) for m in rows[0].months] == ["0.00", "0.00"]
    assert all(str(m.amount) == "0.00" for r in rows[1:] for m in r.months)
