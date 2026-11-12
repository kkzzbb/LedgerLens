"""`GET /api/accounts`: stored bank accounts with their last balance and sync.

The query lives in `db/repositories/bank.py`. The session factory comes from
a dependency that tests replace through `app.dependency_overrides`.
"""

from datetime import datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ledgerlens.db.models import BankAccount
from ledgerlens.db.repositories.bank import list_bank_accounts
from ledgerlens.db.session import get_sessionmaker
from ledgerlens.services.sync import SessionFactory

router = APIRouter(prefix="/api", tags=["accounts"])

CENT = Decimal("0.01")


class AccountResponse(BaseModel):
    id: int
    provider: str
    external_account_id: str
    display_name: str
    currency: str
    # Exactly 2 decimals, e.g. "-5000.00"; never a float. Null before the first sync.
    last_balance: str | None
    last_balance_at: datetime | None
    last_sync_at: datetime | None
    last_sync_status: str | None
    last_sync_error: str | None
    last_successful_sync_at: datetime | None


class AccountListResponse(BaseModel):
    accounts: list[AccountResponse]


def get_session_factory() -> SessionFactory:
    return get_sessionmaker()


@router.get("/accounts", response_model=AccountListResponse)
def accounts(
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
) -> AccountListResponse:
    """Every stored account, ordered by `id`."""
    with session_factory() as session:
        items = [_item(row) for row in list_bank_accounts(session)]
    return AccountListResponse(accounts=items)


def _item(row: BankAccount) -> AccountResponse:
    return AccountResponse(
        id=row.id,
        provider=row.provider,
        external_account_id=row.external_account_id,
        display_name=row.display_name,
        currency=row.currency,
        last_balance=None if row.last_balance is None else str(row.last_balance.quantize(CENT)),
        last_balance_at=row.last_balance_at,
        last_sync_at=row.last_sync_at,
        last_sync_status=row.last_sync_status,
        last_sync_error=row.last_sync_error,
        last_successful_sync_at=row.last_successful_sync_at,
    )
