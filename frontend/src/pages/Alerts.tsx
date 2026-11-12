import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { ApiError, getAnomalies, reviewAnomaly } from "../api/client.ts";
import type {
  AnomalyFlagResponse,
  AnomalyParams,
  FlaggedTransactionResponse,
} from "../api/types.ts";
import { EmptyState } from "../components/EmptyState.tsx";
import { ErrorMessage } from "../components/ErrorMessage.tsx";
import { Loading } from "../components/Loading.tsx";
import { formatMoney } from "../money.ts";

const PAGE_SIZE = 50;

type Status = "" | "open" | "reviewed";
type Rule = "" | "possible_duplicate" | "large_expense";

// Flags are potential issues for a person to review, never fraud or errors
// (docs/accounting-rules.md, Anomaly rules).
const RULE_LABELS: Record<string, string> = {
  possible_duplicate: "Possible duplicate payment",
  large_expense: "Unusually large expense",
};

function toApiError(error: Error): ApiError {
  return error instanceof ApiError ? error : new ApiError(0, error.message);
}

function related(tx: FlaggedTransactionResponse | null): string {
  if (tx === null) return "—";
  return [
    tx.booking_date,
    tx.counterparty_name ?? "—",
    formatMoney(tx.amount),
  ].join(" · ");
}

export function Alerts() {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<Status>("open");
  const [rule, setRule] = useState<Rule>("");
  const [offset, setOffset] = useState(0);

  // Empty values are dropped from the query string by getAnomalies.
  const params: AnomalyParams = {
    status: status || undefined,
    rule: rule || undefined,
    limit: PAGE_SIZE,
    offset,
  };

  const query = useQuery({
    queryKey: ["anomalies", params],
    queryFn: () => getAnomalies(params),
    retry: false,
  });

  const review = useMutation({
    mutationFn: reviewAnomaly,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["anomalies"] }),
  });

  function statusCell(flag: AnomalyFlagResponse) {
    if (flag.status !== "open") return "Reviewed";
    return (
      <button
        type="button"
        disabled={review.isPending && review.variables === flag.id}
        onClick={() => {
          review.mutate(flag.id);
        }}
      >
        Mark reviewed
      </button>
    );
  }

  let content;
  if (query.isPending) {
    content = <Loading />;
  } else if (query.isError) {
    content = <ErrorMessage error={toApiError(query.error)} />;
  } else if (query.data.total === 0) {
    content = (
      <EmptyState
        message={
          status === "open"
            ? "No potential issues to review."
            : "No potential issues."
        }
      />
    );
  } else {
    const { items, total } = query.data;
    const first = offset + 1;
    const last = offset + items.length;
    content = (
      <>
        <table>
          <thead>
            <tr>
              <th scope="col">Rule</th>
              <th scope="col">Date</th>
              <th scope="col">Counterparty</th>
              <th scope="col">Amount</th>
              <th scope="col">Category</th>
              <th scope="col">Reason</th>
              <th scope="col">Related transaction</th>
              <th scope="col">Status</th>
            </tr>
          </thead>
          <tbody>
            {items.map((flag) => (
              <tr key={flag.id}>
                <td>{RULE_LABELS[flag.rule] ?? flag.rule}</td>
                <td>{flag.transaction.booking_date}</td>
                <td>{flag.transaction.counterparty_name ?? "—"}</td>
                <td>{formatMoney(flag.transaction.amount)}</td>
                <td>{flag.transaction.category ?? "Uncategorized"}</td>
                <td>{flag.reason}</td>
                <td>{related(flag.related_transaction)}</td>
                <td>{statusCell(flag)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <nav aria-label="Pagination">
          <button
            type="button"
            disabled={offset === 0}
            onClick={() => {
              setOffset(Math.max(0, offset - PAGE_SIZE));
            }}
          >
            Previous
          </button>
          <span>
            {first}–{last} of {total}
          </span>
          <button
            type="button"
            disabled={offset + PAGE_SIZE >= total}
            onClick={() => {
              setOffset(offset + PAGE_SIZE);
            }}
          >
            Next
          </button>
        </nav>
      </>
    );
  }

  return (
    <>
      <h1>Alerts</h1>
      <div>
        <label>
          Status{" "}
          <select
            value={status}
            onChange={(event) => {
              setStatus(event.target.value as Status);
              setOffset(0);
            }}
          >
            <option value="open">Open</option>
            <option value="reviewed">Reviewed</option>
            <option value="">All</option>
          </select>
        </label>
        <label>
          Rule{" "}
          <select
            value={rule}
            onChange={(event) => {
              setRule(event.target.value as Rule);
              setOffset(0);
            }}
          >
            <option value="">All rules</option>
            <option value="possible_duplicate">
              {RULE_LABELS.possible_duplicate}
            </option>
            <option value="large_expense">{RULE_LABELS.large_expense}</option>
          </select>
        </label>
      </div>
      {review.isError && <ErrorMessage error={toApiError(review.error)} />}
      {content}
    </>
  );
}
