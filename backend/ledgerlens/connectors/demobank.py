"""The DemoBank connector: a thin synchronous client for the `/v1` API.

It returns DemoBank's records unchanged (no value is converted) and turns
every failure into a `ConnectorError`. Neither the API key nor any response
body ever reaches an error message or a log.
"""

from types import TracebackType
from typing import Any, Self, TypeGuard
from urllib.parse import quote

import httpx

from ledgerlens.config import Settings
from ledgerlens.connectors.base import ConnectorError, TransactionPage

CONNECT_TIMEOUT_SECONDS = 3.0
READ_TIMEOUT_SECONDS = 10.0
MIN_LIMIT = 1
MAX_LIMIT = 500


class DemoBankConnector:
    """Implements `BankConnector` against DemoBank."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        transport: httpx.BaseTransport | None = None,
        connect_timeout: float = CONNECT_TIMEOUT_SECONDS,
        read_timeout: float = READ_TIMEOUT_SECONDS,
    ) -> None:
        self._client = httpx.Client(
            base_url=base_url,
            headers={"X-API-Key": api_key},
            timeout=httpx.Timeout(read_timeout, connect=connect_timeout),
            transport=transport,
        )

    @classmethod
    def from_settings(cls, settings: Settings) -> "DemoBankConnector":
        """Built from `DEMOBANK_BASE_URL` and `DEMOBANK_API_KEY`."""
        return cls(settings.demobank_base_url, settings.demobank_api_key.get_secret_value())

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def list_accounts(self) -> list[dict[str, Any]]:
        body = self._get("/v1/accounts")
        if not _is_list_of_dicts(body):
            raise _invalid_response()
        return list(body)

    def get_balance(self, account_id: str) -> dict[str, Any]:
        body = self._get(f"/v1/accounts/{quote(account_id, safe='')}/balance")
        if not isinstance(body, dict):
            raise _invalid_response()
        return body

    def fetch_transactions(
        self, account_id: str, cursor: str | None, limit: int
    ) -> TransactionPage:
        if not MIN_LIMIT <= limit <= MAX_LIMIT:
            raise ValueError(f"limit must be between {MIN_LIMIT} and {MAX_LIMIT}")
        params: dict[str, str | int] = {"limit": limit}
        if cursor is not None:
            params["cursor"] = cursor
        body = self._get(f"/v1/accounts/{quote(account_id, safe='')}/transactions", params)
        if not isinstance(body, dict):
            raise _invalid_response()
        records = body.get("transactions")
        next_cursor = body.get("next_cursor")
        has_more = body.get("has_more")
        if (
            not _is_list_of_dicts(records)
            or not (next_cursor is None or isinstance(next_cursor, str))
            or not isinstance(has_more, bool)
            or "next_cursor" not in body
        ):
            raise _invalid_response()
        return TransactionPage(records=list(records), next_cursor=next_cursor, has_more=has_more)

    def _get(self, path: str, params: dict[str, str | int] | None = None) -> Any:
        """The decoded JSON body of a successful GET, or a `ConnectorError`."""
        error: ConnectorError | None = None
        try:
            response = self._client.get(path, params=params)
        except httpx.TimeoutException:
            error = ConnectorError("timeout", "DemoBank did not respond in time")
        except httpx.TransportError:
            error = ConnectorError("connection", "could not connect to DemoBank")
        except httpx.DecodingError:
            error = _invalid_response()
        except httpx.HTTPError:
            # Last resort, so that no httpx exception escapes the connector.
            error = ConnectorError("http_error", "the request to DemoBank failed")
        # Raised outside the `except` blocks so no httpx exception is chained.
        if error is not None:
            raise error
        if response.status_code >= 400:
            raise _status_error(response)
        try:
            return response.json()
        except ValueError:
            pass
        raise _invalid_response()


def _status_error(response: httpx.Response) -> ConnectorError:
    status = response.status_code
    if status == 401:
        return ConnectorError("unauthorized", "DemoBank rejected the API key")
    if status == 404:
        return ConnectorError("account_not_found", "DemoBank does not know this account")
    if status == 400 and _error_code(response) == "invalid_cursor":
        return ConnectorError("invalid_cursor", "DemoBank rejected the cursor")
    return ConnectorError("http_error", f"DemoBank answered with HTTP {status}")


def _error_code(response: httpx.Response) -> str | None:
    try:
        body = response.json()
    except ValueError:
        return None
    if isinstance(body, dict) and isinstance(body.get("error"), str):
        return str(body["error"])
    return None


def _is_list_of_dicts(value: object) -> TypeGuard[list[dict[str, Any]]]:
    return isinstance(value, list) and all(isinstance(item, dict) for item in value)


def _invalid_response() -> ConnectorError:
    return ConnectorError("invalid_response", "DemoBank sent an unexpected response")
