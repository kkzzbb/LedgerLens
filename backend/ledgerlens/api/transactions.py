"""`GET /api/transactions`: stored bank transactions, filtered and paged.
`GET /api/categories`: the fixed category list, without touching the database.

The query lives in `db/repositories/transactions.py`. The session factory
comes from a dependency that tests replace through `app.dependency_overrides`.
"""

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from ledgerlens.db.models import BankTransaction
from ledgerlens.db.repositories.transactions import TransactionFilters, list_transactions
from ledgerlens.db.session import get_sessionmaker
from ledgerlens.domain.categories import CATEGORIES, CategoryKey, Kind
from ledgerlens.services.sync import SessionFactory

router = APIRouter(prefix="/api", tags=["transactions"])

CENT = Decimal("0.01")


class TransactionResponse(BaseModel):
    id: int
    account_id: int
    booking_date: date
    value_date: date | None
    # Exactly 2 decimals, e.g. "1234.50"; never a float.
    amount: str
    currency: str
    direction: str
    counterparty_name: str | None
    counterparty_reference: str | None
    description: str | None
    status: str
    # A category key, or null while the row is not categorized yet.
    category: str | None


class TransactionListResponse(BaseModel):
    items: list[TransactionResponse]
    total: int
    limit: int
    offset: int


class CategoryResponse(BaseModel):
    key: str
    name: str
    kind: Kind


class CategoryListResponse(BaseModel):
    items: list[CategoryResponse]


def get_session_factory() -> SessionFactory:
    return get_sessionmaker()


@router.get("/transactions", response_model=TransactionListResponse)
def transactions(
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    account_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    direction: Literal["debit", "credit"] | None = None,
    q: str | None = None,
    category: CategoryKey | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> TransactionListResponse:
    """Newest first (`booking_date`, then `id`); dates are inclusive booking dates."""
    if date_from is not None and date_to is not None and date_from > date_to:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="date_from must not be after date_to",
        )
    filters = TransactionFilters(
        account_id=account_id,
        date_from=date_from,
        date_to=date_to,
        direction=direction,
        q=q,
        category=category,
    )
    with session_factory() as session:
        page = list_transactions(session, filters, limit, offset)
        items = [_item(row) for row in page.items]
    return TransactionListResponse(items=items, total=page.total, limit=limit, offset=offset)


@router.get("/categories", response_model=CategoryListResponse)
def categories() -> CategoryListResponse:
    """Every category, in the order of the fixed list."""
    return CategoryListResponse(
        items=[CategoryResponse(key=c.key, name=c.name, kind=c.kind) for c in CATEGORIES]
    )


def _item(row: BankTransaction) -> TransactionResponse:
    return TransactionResponse(
        id=row.id,
        account_id=row.bank_account_id,
        booking_date=row.booking_date,
        value_date=row.value_date,
        amount=str(row.amount.quantize(CENT)),
        currency=row.currency,
        direction=row.direction,
        counterparty_name=row.counterparty_name,
        counterparty_reference=row.counterparty_reference,
        description=row.description,
        status=row.status,
        category=row.category,
    )
