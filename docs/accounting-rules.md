# Accounting rules

The financial conventions LedgerLens follows. The accounting reviewer checks issues and code against this file. If an issue or the code disagrees with it, one of them is wrong. Fix the code, or change this file on purpose and say so in the issue.

Status: written from `docs/outdated/plan.md` §9 and the decisions made while grooming the issues. Cut to the slim scope on 2026-11-12 (`docs/scope.md`): invoices, aging, reconciliation, profitability and AI rules were removed with their features.

LedgerLens is a simplified management tool for one EUR retail business.
It is not a general ledger and not statutory accounting.

## Money

- Amounts are `Decimal` in Python, `NUMERIC(14,2)` in PostgreSQL, and
  strings with exactly 2 decimals in JSON (`"1234.50"`). Never float
- Currency is stored explicitly and is always `EUR` in the MVP
- Rounding is `ROUND_HALF_UP` to 2 decimals: `0.005` → `0.01`,
  `-0.005` → `-0.01`, `2.675` → `2.68` (#5)
- Round once, at the end of a calculation. Intermediate values keep
  full precision
- Largest supported value: 999,999,999,999.99

## Bank transactions

- `amount` is always positive. `direction` (`debit` = money out,
  `credit` = money in) carries the sign
- Imported bank facts (dates, amount, direction, counterparty,
  reference, description) are never changed after import. Category,
  matches and anomalies are stored separately
- Account balance = opening balance + sum of credits - sum of debits
- Periods use the booking date and are inclusive at both ends

## Categories

- A credit can only be `revenue` (or `other`). A debit can only be an
  expense category (or `other`)
- Categories come from rules only. There are no manual corrections in
  the slim scope

## Anomaly rules

Every flag is a potential issue for a person to review. It is never a finding of fraud or error. Thresholds are settings. The defaults below are demo values.

| Rule | Flags | Settings (default) |
|---|---|---|
| Possible duplicate payment (#28) | A debit to the same counterparty, amount within tolerance, within the window | `ANOMALY_DUPLICATE_WINDOW_DAYS` (3), `ANOMALY_DUPLICATE_AMOUNT_TOLERANCE_PERCENT` (1) |
| Unusually large expense (#30) | A debit above the absolute limit, or above a multiple of the vendor or category average | `ANOMALY_LARGE_EXPENSE_ABSOLUTE` (5000.00), `ANOMALY_LARGE_EXPENSE_MULTIPLIER` (3), `ANOMALY_MIN_HISTORY_COUNT` (3), `ANOMALY_BASELINE_DAYS` (90) |

- Transaction rules only evaluate transactions booked within
  `ANOMALY_EVALUATION_WINDOW_DAYS` (7). Older records are the baseline,
  so the first import of six months of history does not flood the
  queue (#32)
- Limits are exceeded only when the value is strictly greater. Window boundaries are inclusive
