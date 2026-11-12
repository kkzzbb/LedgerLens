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


class SyncResponse(BaseModel):
    accounts: list[AccountSyncResponse]


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
    """200 with one result per account (a failed account included); 502 when listing fails."""
    try:
        results = run_sync(connector, session_factory, utc_now, settings.sync_page_size)
    except ConnectorError as error:
        kind = error.kind
    else:
        return SyncResponse(
            accounts=[
                AccountSyncResponse(
                    account_id=result.bank_account_id,
                    external_account_id=result.external_account_id,
                    status=result.status,
                    created_count=result.created_count,
                    skipped_count=result.skipped_count,
                    rejected_count=result.rejected_count,
                    error=result.error,
                )
                for result in results
            ]
        )
    # Raised outside the `except` block so the ConnectorError is not chained.
    raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=kind)
