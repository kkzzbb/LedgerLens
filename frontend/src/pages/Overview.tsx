import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import {
  ApiError,
  getAccounts,
  getMonthlyReport,
  getTransactions,
  runSync,
} from "../api/client.ts";
import type { AccountResponse, TransactionResponse } from "../api/types.ts";
import { EmptyState } from "../components/EmptyState.tsx";
import { ErrorMessage } from "../components/ErrorMessage.tsx";
import { Loading } from "../components/Loading.tsx";
import { formatMoney } from "../money.ts";
import { lastMonths } from "../months.ts";

const RECENT_LIMIT = 5;
const MONTHLY_MONTHS = 6;

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

export function Overview({ today = new Date() }: { today?: Date }) {
  const queryClient = useQueryClient();
  const [range] = useState(() => lastMonths(today, MONTHLY_MONTHS));

  const monthly = useQuery({
    queryKey: ["reports", "monthly", range.from, range.to],
    queryFn: () => getMonthlyReport(range.from, range.to),
    retry: false,
  });

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
        queryClient.invalidateQueries({ queryKey: ["anomalies"] }),
      ]),
  });

  let syncResult;
  if (sync.isSuccess) {
    const anomalies = sync.data.anomalies;
    const created = anomalies.reduce((sum, a) => sum + a.created_count, 0);
    const text = `New potential issues: ${String(created)}`;
    syncResult = (
      <>
        <p>{created > 0 ? <Link to="/alerts">{text}</Link> : text}</p>
        {anomalies.some((a) => a.error !== null) && (
          <p>Some anomaly checks did not run</p>
        )}
      </>
    );
  }

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

  let monthlyContent;
  if (monthly.isPending) {
    monthlyContent = <Loading />;
  } else if (monthly.isError) {
    monthlyContent = <ErrorMessage error={toApiError(monthly.error)} />;
  } else if (
    monthly.data.months.every(
      (m) => m.money_in === "0.00" && m.money_out === "0.00",
    )
  ) {
    monthlyContent = <EmptyState message="No transactions in this period." />;
  } else {
    const currency = monthly.data.currency;
    monthlyContent = (
      <table>
        <thead>
          <tr>
            <th scope="col">Month</th>
            <th scope="col">Money in</th>
            <th scope="col">Money out</th>
            <th scope="col">Net</th>
          </tr>
        </thead>
        <tbody>
          {monthly.data.months.map((m) => (
            <tr key={m.month}>
              <td>{m.month}</td>
              <td>{formatMoney(m.money_in, currency)}</td>
              <td>{formatMoney(m.money_out, currency)}</td>
              <td>{formatMoney(m.net, currency)}</td>
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
          {syncResult}
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
      <section aria-labelledby="monthly-heading">
        <h2 id="monthly-heading">Money in / out per month</h2>
        {monthlyContent}
      </section>
    </>
  );
}
