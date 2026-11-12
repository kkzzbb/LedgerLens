"""`GET /health`: is the DemoBank process up?

Public: it needs no API key. A liveness check only: it touches no database,
now or later, so it stays 200 while the failure scenarios (#13) make the
`/v1/*` routes fail.
"""

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    """The service is up."""

    status: Literal["ok"]


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Always 200 `{"status": "ok"}` while the process serves requests."""
    return HealthResponse(status="ok")
