"""`POST /api/sync`: run one synchronization of every bank account now.

The route holds no logic of its own. The connector and the session factory
come from dependencies that tests replace through `app.dependency_overrides`.
"""

from collections.abc import Iterator
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from ledgerlens.config import Settings, get_settings
from ledgerlens.connectors.base import BankConnector, ConnectorError
from ledgerlens.connectors.demobank import DemoBankConnector
from ledgerlens.db.session import get_sessionmaker
from ledgerlens.services.sync import SessionFactory, run_sync, utc_now

router = APIRouter(prefix="/api", tags=["sync"])


class AccountSyncResponse(BaseModel):
    account_id: int
    external_account_id: str
    status: str
    created_count: int
    skipped_count: int
    rejected_count: int
    error: str | None


class AnomalyRuleResponse(BaseModel):
    rule: str
    created_count: int
    error: str | None


class SyncResponse(BaseModel):
    accounts: list[AccountSyncResponse]
    anomalies: list[AnomalyRuleResponse]


def get_connector(settings: Annotated[Settings, Depends(get_settings)]) -> Iterator[BankConnector]:
    """The DemoBank connector, closed after the request."""
    with DemoBankConnector.from_settings(settings) as connector:
        yield connector


def get_session_factory() -> SessionFactory:
    return get_sessionmaker()


@router.post(
    "/sync",
    response_model=SyncResponse,
    responses={status.HTTP_502_BAD_GATEWAY: {"description": "The bank could not list accounts"}},
)
def sync(
    settings: Annotated[Settings, Depends(get_settings)],
    connector: Annotated[BankConnector, Depends(get_connector)],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
) -> SyncResponse:
    """200 with one result per account and per anomaly rule; 502 when listing fails."""
    try:
        result = run_sync(connector, session_factory, utc_now, settings)
    except ConnectorError as error:
        kind = error.kind
    else:
        return SyncResponse(
            accounts=[
                AccountSyncResponse(
                    account_id=account.bank_account_id,
                    external_account_id=account.external_account_id,
                    status=account.status,
                    created_count=account.created_count,
                    skipped_count=account.skipped_count,
                    rejected_count=account.rejected_count,
                    error=account.error,
                )
                for account in result.accounts
            ],
            anomalies=[
                AnomalyRuleResponse(rule=a.rule, created_count=a.created_count, error=a.error)
                for a in result.anomalies
            ],
        )
    # Raised outside the `except` block so the ConnectorError is not chained.
    raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=kind)
