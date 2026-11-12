"""The API key check shared by every `/v1/*` route.

The `/v1` router carries `require_api_key` once, so a route added to it is
protected without doing anything. A request without the correct key gets 401
`{"error": "unauthorized"}`, the same body whatever was wrong, so a caller
cannot tell a missing key from a wrong one. The key is never logged and never
echoed.
"""

import hmac
from typing import Annotated

from fastapi import Depends, Request
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader

from demobank.config import get_settings

API_KEY_HEADER = "X-API-Key"

# `auto_error=False`: a missing header reaches `require_api_key`, which answers
# with the same 401 as for a wrong key. The scheme also documents the header in
# `/openapi.json`. Header names are case-insensitive.
_api_key_header = APIKeyHeader(
    name=API_KEY_HEADER,
    scheme_name="ApiKeyHeader",
    description="The DemoBank API key (`DEMOBANK_API_KEY`).",
    auto_error=False,
)


class UnauthorizedError(Exception):
    """The request has no valid API key. Carries no detail on purpose."""


def _received_bytes(value: str) -> bytes:
    # Starlette decodes header values as Latin-1, which maps every byte to one
    # character, so encoding back as Latin-1 gives the exact bytes the client
    # sent. Nothing is stripped: the value is compared as sent.
    return value.encode("latin-1")


def require_api_key(
    received: Annotated[str | None, Depends(_api_key_header)],
) -> None:
    """Passes only when `X-API-Key` holds exactly `DEMOBANK_API_KEY`."""
    expected = get_settings().demobank_api_key.get_secret_value().encode("utf-8")
    # An empty or missing value is compared too (against the non-empty key),
    # so every rejected case takes the same path.
    sent = _received_bytes(received) if received is not None else b""
    if not hmac.compare_digest(sent, expected):
        raise UnauthorizedError


async def unauthorized_handler(request: Request, exc: Exception) -> JSONResponse:
    """401 `{"error": "unauthorized"}`. Writes no log line of its own."""
    return JSONResponse(status_code=401, content={"error": "unauthorized"})
