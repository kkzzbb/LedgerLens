"""`GET /api/reports/monthly`: money in, money out and net per month.
`GET /api/reports/expenses`: debits per expense category per month.

Both take `from` and `to` as `YYYY-MM`. The sums are queried in
`db/repositories/reports.py`; the range and the zero-filling are in
`domain/reports.py`. The session factory comes from a dependency that tests
replace through `app.dependency_overrides`.
"""

from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from ledgerlens.db.repositories.reports import (
    debit_sums_by_category_and_month,
    sums_by_month_and_direction,
)
from ledgerlens.db.session import get_sessionmaker
from ledgerlens.domain.money import CURRENCY
from ledgerlens.domain.reports import (
    MonthRange,
    MonthRangeError,
    expense_figures,
    month_range,
    monthly_figures,
)
from ledgerlens.services.sync import SessionFactory

router = APIRouter(prefix="/api/reports", tags=["reports"])

FromMonth = Annotated[str, Query(alias="from", description="First month, YYYY-MM")]
ToMonth = Annotated[str, Query(alias="to", description="Last month, YYYY-MM")]


# Every amount is a string with exactly 2 decimals, e.g. "-120.00"; never a float.
class MonthResponse(BaseModel):
    month: str
    money_in: str
    money_out: str
    net: str


class MonthlyReportResponse(BaseModel):
    from_: str = Field(serialization_alias="from")
    to: str
    currency: str
    months: list[MonthResponse]


class MonthAmountResponse(BaseModel):
    month: str
    amount: str


class CategoryReportResponse(BaseModel):
    key: str
    name: str
    total: str
    months: list[MonthAmountResponse]


class ExpensesReportResponse(BaseModel):
    from_: str = Field(serialization_alias="from")
    to: str
    currency: str
    categories: list[CategoryReportResponse]


def get_session_factory() -> SessionFactory:
    return get_sessionmaker()


@router.get("/monthly", response_model=MonthlyReportResponse)
def monthly(
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    from_month: FromMonth,
    to_month: ToMonth,
) -> MonthlyReportResponse:
    """One entry per month, oldest first; every transaction of every account counts."""
    period = _range(from_month, to_month)
    with session_factory() as session:
        sums = sums_by_month_and_direction(session, period.first_day, period.last_day)
    money_in = {month: total for (month, direction), total in sums.items() if direction == "credit"}
    money_out = {month: total for (month, direction), total in sums.items() if direction == "debit"}
    rows = monthly_figures(period.months, money_in, money_out)
    return MonthlyReportResponse(
        from_=from_month,
        to=to_month,
        currency=CURRENCY,
        months=[
            MonthResponse(
                month=row.month,
                money_in=_text(row.money_in),
                money_out=_text(row.money_out),
                net=_text(row.net),
            )
            for row in rows
        ],
    )


@router.get("/expenses", response_model=ExpensesReportResponse)
def expenses(
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    from_month: FromMonth,
    to_month: ToMonth,
) -> ExpensesReportResponse:
    """Debits per expense category, in the order of `CATEGORIES`; null counts as `other`."""
    period = _range(from_month, to_month)
    with session_factory() as session:
        debits = debit_sums_by_category_and_month(session, period.first_day, period.last_day)
    rows = expense_figures(period.months, debits)
    return ExpensesReportResponse(
        from_=from_month,
        to=to_month,
        currency=CURRENCY,
        categories=[
            CategoryReportResponse(
                key=row.key,
                name=row.name,
                total=_text(row.total),
                months=[
                    MonthAmountResponse(month=item.month, amount=_text(item.amount))
                    for item in row.months
                ],
            )
            for row in rows
        ],
    )


def _range(from_month: str, to_month: str) -> MonthRange:
    try:
        return month_range(from_month, to_month)
    except MonthRangeError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from None


def _text(value: Decimal) -> str:
    # Already rounded to exactly 2 decimals, once, in the domain.
    return str(value)
