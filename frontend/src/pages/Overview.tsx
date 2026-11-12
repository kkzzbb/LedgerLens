import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import {
  ApiError,
  getAccounts,
  getTransactions,
  runSync,
} from "../api/client.ts";
import type { AccountResponse, TransactionResponse } from "../api/types.ts";
import { EmptyState } from "../components/EmptyState.tsx";
import { ErrorMessage } from "../components/ErrorMessage.tsx";
import { Loading } from "../components/Loading.tsx";
import { formatMoney } from "../money.ts";

const RECENT_LIMIT = 5;

function toApiError(error: Error): ApiError {
  return error instanceof ApiError ? error : new ApiError(0, error.message);
}

// Datetimes come with an offset; they are shown in UTC as YYYY-MM-DD HH:MM UTC.
function formatUtc(value: string): string {
  return `${new Date(value).toISOString().slice(0, 16).replace("T", " ")} UTC`;
}

function statusText(account: AccountResponse): string {
  const status = account.last_sync_status ?? "";
  const error = account.last_sync_error ?? "";
  switch (status) {
    case "succeeded":
      return "Synced";
    case "succeeded_with_errors":
      return `Synced with errors: ${error}`;
    case "failed":
      return `Sync failed: ${error}`;
    default:
      return status;
  }
}

// Amounts are always positive strings; the direction carries the sign.
function signedAmount(tx: TransactionResponse): string {
  const amount = tx.direction === "debit" ? `-${tx.amount}` : tx.amount;
  return formatMoney(amount, tx.currency);
}

function AccountCard({ account }: { account: AccountResponse }) {
  return (
    <article aria-label={account.display_name}>
      <h3>{account.display_name}</h3>
      {account.last_sync_status === null ? (
        <p>Waiting for first sync</p>
      ) : (
        <>
          {account.last_balance !== null && (
            <p>{formatMoney(account.last_balance, account.currency)}</p>
          )}
          <p>{statusText(account)}</p>
          {account.last_sync_at !== null && (
            <p>{formatUtc(account.last_sync_at)}</p>
          )}
          {account.last_sync_status === "failed" &&
            account.last_successful_sync_at !== null && (
              <p>
                Last successful sync:{" "}
                {formatUtc(account.last_successful_sync_at)}
              </p>
            )}
        </>
      )}
    </article>
  );
}

export function Overview() {
  const queryClient = useQueryClient();

  const accounts = useQuery({
    queryKey: ["accounts"],
    queryFn: getAccounts,
    retry: false,
  });

  const recentParams = { limit: RECENT_LIMIT };
  const recent = useQuery({
    queryKey: ["transactions", recentParams],
    queryFn: () => getTransactions(recentParams),
    retry: false,
  });

  const sync = useMutation({
    mutationFn: runSync,
    onSuccess: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: ["accounts"] }),
        queryClient.invalidateQueries({ queryKey: ["transactions"] }),
      ]),
  });

  let accountsContent;
  if (accounts.isPending) {
    accountsContent = <Loading />;
  } else if (accounts.isError) {
    accountsContent = <ErrorMessage error={toApiError(accounts.error)} />;
  } else if (accounts.data.accounts.length === 0) {
    accountsContent = (
      <EmptyState message="No accounts yet. Run a sync to load them." />
    );
  } else {
    accountsContent = accounts.data.accounts.map((account) => (
      <AccountCard key={account.id} account={account} />
    ));
  }

  let recentContent;
  if (recent.isPending) {
    recentContent = <Loading />;
  } else if (recent.isError) {
    recentContent = <ErrorMessage error={toApiError(recent.error)} />;
  } else if (recent.data.items.length === 0) {
    recentContent = <EmptyState message="No transactions yet." />;
  } else {
    recentContent = (
      <table>
        <thead>
          <tr>
            <th scope="col">Date</th>
            <th scope="col">Counterparty</th>
            <th scope="col">Amount</th>
          </tr>
        </thead>
        <tbody>
          {recent.data.items.map((tx) => (
            <tr key={tx.id}>
              <td>{tx.booking_date}</td>
              <td>{tx.counterparty_name ?? tx.description ?? "—"}</td>
              <td>{signedAmount(tx)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    );
  }

  return (
    <>
      <h1>Overview</h1>
      <section aria-labelledby="accounts-heading">
        <h2 id="accounts-heading">Accounts</h2>
        <div>
          <button
            type="button"
            disabled={sync.isPending}
            onClick={() => {
              sync.mutate();
            }}
          >
            {sync.isPending ? "Syncing…" : "Sync now"}
          </button>
          {sync.isError && (
            <p role="alert">Sync failed: {toApiError(sync.error).message}</p>
          )}
        </div>
        {accountsContent}
      </section>
      <section aria-labelledby="recent-heading">
        <h2 id="recent-heading">Recent transactions</h2>
        {recentContent}
        <Link to="/transactions">All transactions</Link>
      </section>
    </>
  );
}
