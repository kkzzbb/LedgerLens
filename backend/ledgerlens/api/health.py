"""`GET /api/health`: is the service up, and can it reach its database?

Public: it needs no authentication. The route holds no logic of its own; the
check comes from `get_database_check`, which tests replace through
`app.dependency_overrides`, and the deadline from the health service.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel

from ledgerlens.db.session import get_engine
from ledgerlens.services.health import DatabaseCheck, passes_within_deadline, select_one

router = APIRouter(prefix="/api", tags=["health"])


class HealthResponse(BaseModel):
    """The health of the service and of its database."""

    status: Literal["ok", "degraded"]
    database: Literal["ok", "unavailable"]


HEALTHY = HealthResponse(status="ok", database="ok")
DEGRADED = HealthResponse(status="degraded", database="unavailable")


def _check_application_database() -> bool:
    # `get_engine()` is called inside the check, so a failure to build the
    # engine also counts as "unavailable".
    return select_one(get_engine())


def get_database_check() -> DatabaseCheck:
    """The database check the route runs: `SELECT 1` on the application engine."""
    return _check_application_database


@router.get(
    "/health",
    response_model=HealthResponse,
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": HealthResponse}},
)
def health(
    response: Response,
    check: Annotated[DatabaseCheck, Depends(get_database_check)],
) -> HealthResponse:
    """200 when the database answers within the deadline, otherwise 503."""
    if passes_within_deadline(check):
        return HEALTHY
    response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return DEGRADED
