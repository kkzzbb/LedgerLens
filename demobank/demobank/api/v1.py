"""The `/v1` router. Every route on it requires the API key.

The key check is a dependency of the router itself, not of each route, so the
routes added later (#11, #13) are protected by construction.
"""

from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import Engine

from demobank.api.auth import require_api_key
from demobank.db.accounts import account_balance, list_accounts

router = APIRouter(prefix="/v1", tags=["v1"], dependencies=[Depends(require_api_key)])


class PingResponse(BaseModel):
    """The caller reached DemoBank with a valid key."""

    status: Literal["ok"]


@router.get("/ping", response_model=PingResponse)
def ping() -> PingResponse:
    """An authenticated connectivity check: 200 `{"status": "ok"}`."""
    return PingResponse(status="ok")


def get_engine(request: Request) -> Engine:
    """The engine the app created at startup. `db` tests override this dependency."""
    engine: Engine = request.app.state.engine
    return engine


EngineDependency = Annotated[Engine, Depends(get_engine)]

CENT = Decimal("0.01")


class AccountResponse(BaseModel):
    account_id: str
    display_name: str
    currency: str


class BalanceResponse(BaseModel):
    """`balance` is a string with exactly 2 decimals, never a JSON number."""

    account_id: str
    balance: str
    currency: str
    as_of: str


class ErrorResponse(BaseModel):
    error: str


@router.get("/accounts", response_model=list[AccountResponse])
def get_accounts(engine: EngineDependency) -> list[AccountResponse]:
    """Every account, ordered by `account_id`."""
    return [
        AccountResponse(account_id=a.account_id, display_name=a.display_name, currency=a.currency)
        for a in list_accounts(engine)
    ]


@router.get(
    "/accounts/{account_id}/balance",
    response_model=BalanceResponse,
    responses={404: {"model": ErrorResponse, "description": "Unknown account"}},
)
def get_balance(account_id: str, engine: EngineDependency) -> BalanceResponse | JSONResponse:
    """The current balance, computed from the stored transactions at request time."""
    found = account_balance(engine, account_id)
    if found is None:
        return JSONResponse(status_code=404, content={"error": "account_not_found"})
    return BalanceResponse(
        account_id=found.account_id,
        balance=str(found.balance.quantize(CENT, rounding=ROUND_HALF_UP)),
        currency=found.currency,
        as_of=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
