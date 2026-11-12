"""Monthly report figures (pure): the month range and zero-filled rows.

A month is a `YYYY-MM` string. The range runs from the first day of `from`
to the last day of `to`, both inclusive, and holds at most `MAX_MONTHS`
months. Sums come in as unrounded `Decimal` values keyed by month; every
missing month or category counts as zero, and each figure is rounded once at
the end (`docs/accounting-rules.md`, Money).
"""

import calendar
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Final

from ledgerlens.domain.categories import CATEGORIES, CategoryKey
from ledgerlens.domain.money import round_money

MAX_MONTHS: Final = 24
_MONTH_PATTERN: Final = re.compile(r"[0-9]{4}-(0[1-9]|1[0-2])")
_ZERO: Final = Decimal("0")

# Every category a debit can have, in the order of `CATEGORIES`.
EXPENSE_CATEGORIES: Final = tuple(c for c in CATEGORIES if c.key != "revenue")


class MonthRangeError(ValueError):
    """The month range is not valid."""


@dataclass(frozen=True)
class MonthRange:
    months: tuple[str, ...]
    first_day: date
    last_day: date


@dataclass(frozen=True)
class MonthFigures:
    month: str
    money_in: Decimal
    money_out: Decimal
    net: Decimal


@dataclass(frozen=True)
class MonthAmount:
    month: str
    amount: Decimal


@dataclass(frozen=True)
class CategoryFigures:
    key: CategoryKey
    name: str
    total: Decimal
    months: tuple[MonthAmount, ...]


def _parse(text: str) -> tuple[int, int]:
    if not _MONTH_PATTERN.fullmatch(text) or text.startswith("0000"):
        raise MonthRangeError(f"not a YYYY-MM month: {text!r}")
    return int(text[:4]), int(text[5:])


def month_range(first: str, last: str) -> MonthRange:
    """The months from `first` to `last`, oldest first, with their first and last day."""
    year, month = _parse(first)
    end_year, end_month = _parse(last)
    count = (end_year - year) * 12 + (end_month - month) + 1
    if count < 1:
        raise MonthRangeError("from must not be after to")
    if count > MAX_MONTHS:
        raise MonthRangeError(f"the range must not be longer than {MAX_MONTHS} months")
    months = []
    for index in range(count):
        y, m = divmod(year * 12 + month - 1 + index, 12)
        months.append(f"{y:04d}-{m + 1:02d}")
    last_day = date(end_year, end_month, calendar.monthrange(end_year, end_month)[1])
    return MonthRange(tuple(months), date(year, month, 1), last_day)


def monthly_figures(
    months: tuple[str, ...],
    money_in: Mapping[str, Decimal],
    money_out: Mapping[str, Decimal],
) -> list[MonthFigures]:
    """One row per month; `net` comes from the unrounded sums."""
    rows = []
    for month in months:
        credits = money_in.get(month, _ZERO)
        debits = money_out.get(month, _ZERO)
        rows.append(
            MonthFigures(
                month=month,
                money_in=round_money(credits),
                money_out=round_money(debits),
                net=round_money(credits - debits),
            )
        )
    return rows


def expense_figures(
    months: tuple[str, ...], debits: Mapping[tuple[str, str], Decimal]
) -> list[CategoryFigures]:
    """One row per expense category; `debits` is keyed by `(category, month)`.

    `total` comes from the unrounded monthly sums.
    """
    rows = []
    for category in EXPENSE_CATEGORIES:
        sums = [debits.get((category.key, month), _ZERO) for month in months]
        rows.append(
            CategoryFigures(
                key=category.key,
                name=category.name,
                total=round_money(sum(sums, _ZERO)),
                months=tuple(
                    MonthAmount(month, round_money(amount))
                    for month, amount in zip(months, sums, strict=True)
                ),
            )
        )
    return rows
