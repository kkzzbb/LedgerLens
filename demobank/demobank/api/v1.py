"""The `/v1` router. Every route on it requires the API key.

The key check is a dependency of the router itself, not of each route, so the
routes added later (#10, #11, #13) are protected by construction.
"""

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from demobank.api.auth import require_api_key

router = APIRouter(prefix="/v1", tags=["v1"], dependencies=[Depends(require_api_key)])


class PingResponse(BaseModel):
    """The caller reached DemoBank with a valid key."""

    status: Literal["ok"]


@router.get("/ping", response_model=PingResponse)
def ping() -> PingResponse:
    """An authenticated connectivity check: 200 `{"status": "ok"}`."""
    return PingResponse(status="ok")
