"""`GET /api/anomalies`: stored anomaly flags, filtered and paged.
`POST /api/anomalies/{id}/review`: marks a flag reviewed.

Every flag is a potential issue for a person to review
(`docs/accounting-rules.md`, Anomaly rules). The queries live in
`db/repositories/anomalies.py`. The session factory comes from a dependency
that tests replace through `app.dependency_overrides`.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from ledgerlens.db.models import AnomalyFlag, BankTransaction
from ledgerlens.db.repositories.anomalies import FlagStatus, list_flags, mark_reviewed
from ledgerlens.db.session import get_sessionmaker
from ledgerlens.domain.anomalies import RuleKey
from ledgerlens.services.sync import SessionFactory

router = APIRouter(prefix="/api", tags=["anomalies"])

CENT = Decimal("0.01")


class FlaggedTransactionResponse(BaseModel):
    id: int
    booking_date: date
    counterparty_name: str | None
    # Exactly 2 decimals, e.g. "1250.00"; never a float.
    amount: str
    # A category key, or null while the row is not categorized yet.
    category: str | None


class AnomalyFlagResponse(BaseModel):
    id: int
    rule: str
    status: str
    reason: str
    created_at: datetime
    reviewed_at: datetime | None
    transaction: FlaggedTransactionResponse
    related_transaction: FlaggedTransactionResponse | None


class AnomalyFlagListResponse(BaseModel):
    items: list[AnomalyFlagResponse]
    total: int
    limit: int
    offset: int


def get_session_factory() -> SessionFactory:
    return get_sessionmaker()


@router.get("/anomalies", response_model=AnomalyFlagListResponse)
def anomalies(
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    status: FlagStatus | None = None,
    rule: RuleKey | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AnomalyFlagListResponse:
    """Newest first (`created_at`, then `id`)."""
    with session_factory() as session:
        page = list_flags(session, status, rule, limit, offset)
        items = [_item(flag) for flag in page.items]
    return AnomalyFlagListResponse(items=items, total=page.total, limit=limit, offset=offset)


@router.post("/anomalies/{flag_id}/review", response_model=AnomalyFlagResponse)
def review(
    flag_id: int,
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
) -> AnomalyFlagResponse:
    """Marks the flag reviewed. A flag already reviewed is returned unchanged."""
    with session_factory() as session:
        flag = mark_reviewed(session, flag_id)
        if flag is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="anomaly flag not found"
            )
        item = _item(flag)
        session.commit()
    return item


def _item(flag: AnomalyFlag) -> AnomalyFlagResponse:
    related = flag.related_transaction
    return AnomalyFlagResponse(
        id=flag.id,
        rule=flag.rule,
        status=flag.status,
        reason=flag.reason,
        created_at=flag.created_at,
        reviewed_at=flag.reviewed_at,
        transaction=_transaction(flag.transaction),
        related_transaction=_transaction(related) if related is not None else None,
    )


def _transaction(row: BankTransaction) -> FlaggedTransactionResponse:
    return FlaggedTransactionResponse(
        id=row.id,
        booking_date=row.booking_date,
        counterparty_name=row.counterparty_name,
        amount=str(row.amount.quantize(CENT)),
        category=row.category,
    )
