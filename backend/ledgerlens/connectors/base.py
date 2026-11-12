"""The interface every bank connector implements, and its one error type."""

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class TransactionPage:
    """One page of transactions, the records exactly as the bank sent them."""

    records: list[dict[str, Any]]
    next_cursor: str | None
    has_more: bool


class ConnectorError(Exception):
    """Any connector failure.

    `kind` names the failure. The message is short and fixed: it never holds
    the API key or a response body.
    """

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message

    def __repr__(self) -> str:
        return f"ConnectorError(kind={self.kind!r}, message={self.message!r})"


class BankConnector(Protocol):
    """Reads accounts, balances and transaction pages from one bank."""

    def list_accounts(self) -> list[dict[str, Any]]: ...

    def get_balance(self, account_id: str) -> dict[str, Any]: ...

    def fetch_transactions(
        self, account_id: str, cursor: str | None, limit: int
    ) -> TransactionPage: ...
