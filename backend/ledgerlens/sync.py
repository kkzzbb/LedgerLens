"""`uv run python -m ledgerlens.sync`: run one synchronization of every bank account.

Prints one line per account, `<external_account_id> <status> created=<n>
rejected=<n>[ error=<...>]`. Exit status 1 when the accounts cannot be listed
or any account failed, otherwise 0.
"""

import sys

from ledgerlens.config import load_settings_or_exit
from ledgerlens.connectors.base import ConnectorError
from ledgerlens.connectors.demobank import DemoBankConnector
from ledgerlens.db.session import get_sessionmaker
from ledgerlens.services.sync import FAILED, AccountSyncResult, run_sync, utc_now


def format_result(result: AccountSyncResult) -> str:
    line = (
        f"{result.external_account_id} {result.status}"
        f" created={result.created_count} rejected={result.rejected_count}"
    )
    return line if result.error is None else f"{line} error={result.error}"


def main() -> int:
    settings = load_settings_or_exit()
    try:
        with DemoBankConnector.from_settings(settings) as connector:
            results = run_sync(connector, get_sessionmaker(), utc_now, settings.sync_page_size)
    except ConnectorError as error:
        print(f"sync failed: {error.kind}", file=sys.stderr)
        return 1
    for result in results:
        print(format_result(result))
    return 1 if any(result.status == FAILED for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
