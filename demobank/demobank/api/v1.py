"""The `/v1` router. Every route on it requires the API key.

The key check is a dependency of the router itself, not of each route, so the
routes added later (#11, #13) are protected by construction.
"""

from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import Engine

from demobank.api.auth import require_api_key
from demobank.api.cursor import InvalidCursorError, Position, decode_cursor, encode_cursor
from demobank.db.accounts import account_balance, list_accounts
from demobank.db.transactions import StoredTransaction, account_exists, transactions_page

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


class TransactionResponse(BaseModel):
    """`amount` is a positive string with exactly 2 decimals; dates are `YYYY-MM-DD`."""

    transaction_id: str
    account_id: str
    booking_date: str
    value_date: str
    amount: str
    currency: str
    direction: Literal["debit", "credit"]
    counterparty_name: str
    counterparty_reference: str | None
    description: str | None
    status: str


class TransactionsPageResponse(BaseModel):
    transactions: list[TransactionResponse]
    next_cursor: str | None
    has_more: bool


def _transaction_response(t: StoredTransaction) -> TransactionResponse:
    return TransactionResponse(
        transaction_id=t.transaction_id,
        account_id=t.account_id,
        booking_date=t.booking_date.isoformat(),
        value_date=t.value_date.isoformat(),
        amount=str(t.amount.quantize(CENT, rounding=ROUND_HALF_UP)),
        currency=t.currency,
        direction="debit" if t.direction == "debit" else "credit",
        counterparty_name=t.counterparty_name,
        counterparty_reference=t.counterparty_reference,
        description=t.description,
        status=t.status,
    )


@router.get(
    "/accounts/{account_id}/transactions",
    response_model=TransactionsPageResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid cursor"},
        404: {"model": ErrorResponse, "description": "Unknown account"},
    },
)
def get_transactions(
    account_id: str,
    engine: EngineDependency,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> TransactionsPageResponse | JSONResponse:
    """One page in `(booking_date, transaction_id)` order, strictly after `cursor`."""
    after: Position | None = None
    if cursor:
        try:
            after = decode_cursor(cursor)
        except InvalidCursorError:
            return JSONResponse(status_code=400, content={"error": "invalid_cursor"})
    if not account_exists(engine, account_id):
        return JSONResponse(status_code=404, content={"error": "account_not_found"})
    page = transactions_page(engine, account_id, after, limit)
    if page.transactions:
        last = page.transactions[-1]
        next_cursor: str | None = encode_cursor(Position(last.booking_date, last.transaction_id))
    else:
        next_cursor = cursor or None
    return TransactionsPageResponse(
        transactions=[_transaction_response(t) for t in page.transactions],
        next_cursor=next_cursor,
        has_more=page.has_more,
    )
