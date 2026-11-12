"""Store, list and review anomaly flags.

A flag is a potential issue for a person to review. `insert_flags` never
changes a stored flag, so the rules can run again after every sync. No
function here commits; the caller owns the transaction.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import ColumnElement, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, selectinload

from ledgerlens.db.models import AnomalyFlag
from ledgerlens.domain.anomalies import RuleKey

FlagStatus = Literal["open", "reviewed"]


@dataclass(frozen=True)
class NewFlag:
    rule: RuleKey
    transaction_id: int
    related_transaction_id: int | None
    reason: str


@dataclass(frozen=True)
class FlagPage:
    items: Sequence[AnomalyFlag]
    # Every flag matching the filters, ignoring paging.
    total: int


def insert_flags(session: Session, flags: Sequence[NewFlag]) -> int:
    """Inserts the flags whose (rule, transaction) pair is not stored yet.

    Returns the number of rows inserted. A pair given twice is inserted once.
    """
    if not flags:
        return 0
    rows = [
        {
            "rule": flag.rule,
            "bank_transaction_id": flag.transaction_id,
            "related_transaction_id": flag.related_transaction_id,
            "reason": flag.reason,
        }
        for flag in flags
    ]
    statement = (
        insert(AnomalyFlag)
        .values(rows)
        .on_conflict_do_nothing(index_elements=["rule", "bank_transaction_id"])
        .returning(AnomalyFlag.id)
    )
    return len(session.execute(statement).scalars().all())


def list_flags(
    session: Session,
    status: FlagStatus | None,
    rule: RuleKey | None,
    limit: int,
    offset: int,
) -> FlagPage:
    """Matching flags by `created_at` then `id`, both descending, sliced by `limit`/`offset`."""
    conditions: list[ColumnElement[bool]] = []
    if status is not None:
        conditions.append(AnomalyFlag.status == status)
    if rule is not None:
        conditions.append(AnomalyFlag.rule == rule)
    total = session.scalar(select(func.count()).select_from(AnomalyFlag).where(*conditions))
    items = session.scalars(
        select(AnomalyFlag)
        .where(*conditions)
        .options(
            selectinload(AnomalyFlag.transaction), selectinload(AnomalyFlag.related_transaction)
        )
        .order_by(AnomalyFlag.created_at.desc(), AnomalyFlag.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return FlagPage(items=items, total=total or 0)


def mark_reviewed(session: Session, flag_id: int) -> AnomalyFlag | None:
    """Marks an `open` flag reviewed; a reviewed flag is left as it is.

    Returns the flag as stored afterwards, or None when there is no such flag.
    """
    session.execute(
        update(AnomalyFlag)
        .where(AnomalyFlag.id == flag_id, AnomalyFlag.status == "open")
        .values(status="reviewed", reviewed_at=func.now())
        .execution_options(synchronize_session=False)
    )
    return session.scalars(
        select(AnomalyFlag)
        .where(AnomalyFlag.id == flag_id)
        .options(
            selectinload(AnomalyFlag.transaction), selectinload(AnomalyFlag.related_transaction)
        )
        .execution_options(populate_existing=True)
    ).one_or_none()
