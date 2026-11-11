# Accounting rules

The financial conventions LedgerLens follows. The accounting reviewer checks issues and code against this file. If an issue or the code disagrees with it, one of them is wrong. Fix the code, or change this file on purpose and say so in the issue.

Status: written from `docs/outdated/plan.md` §9 and the decisions made while grooming the issues. #74 checks it against the implementation and adds worked examples linked to tests.

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
- A user's manual category always wins over the rules

## Invoices (payables and receivables)

- `payable` = a supplier bill (we owe). `receivable` = a customer
  invoice (we are owed)
- `outstanding = total - amount_paid`, with `0 <= amount_paid <= total` and `total > 0`
- `due_date >= issue_date`
- An invoice is overdue when `outstanding > 0` and `as_of > due_date`

## Aging

- Days overdue are counted from the due date, never from the invoice date: `days_overdue = as_of - due_date`
- Buckets: `current` (not yet due, or due today), `1_30`, `31_60`, `61_90`, `over_90`
- Fully paid invoices are in no bucket
- The bucket amounts always add up to total outstanding
- `as_of` is always an input. Formulas never read today's date
  themselves

## Reconciliation

- A credit can only match a receivable, and a debit only a payable
- One bank transaction matches at most one invoice. Splitting one
  payment across several invoices is not supported in the MVP
- A payment larger than the invoice's outstanding amount is not
  suggested. A person decides
- Only a person accepts a match. Nothing is accepted automatically, and
  ambiguous suggestions need an explicit confirmation
- Accepting a match adds the transaction amount to the invoice's
  `amount_paid`. The invoice update and the audit record are written in one database transaction
- Score components (0–100): amount equal to outstanding 40 (partial payment 15), invoice number in the reference 30, counterparty name similarity up to 20, date proximity up to 10

## COGS and profitability

Simplified periodic-inventory calculation, per calendar month:

- `COGS = opening inventory + inventory purchases - closing inventory`
- `gross profit = revenue - COGS`
- `gross margin % = gross profit / revenue × 100`, rounded to 2 decimals
- Zero revenue: margin is "not available", not an error
- Negative COGS is reported with a warning (it usually means wrong inventory values)
- Negative gross profit is a valid result
- A month missing an inventory snapshot or revenue is reported as
  incomplete and never flagged
- Each month's opening inventory should equal the previous month's closing inventory. A difference is saved, with a warning

## Anomaly rules

Every flag is a potential issue for a person to review. It is never a finding of fraud or error. Thresholds are settings. The defaults below are demo values.

| Rule | Flags | Settings (default) |
|---|---|---|
| Possible duplicate payment (#28) | A debit to the same counterparty, amount within tolerance, within the window | `ANOMALY_DUPLICATE_WINDOW_DAYS` (3), `ANOMALY_DUPLICATE_AMOUNT_TOLERANCE_PERCENT` (1) |
| Unfamiliar counterparty (#29) | The first debit to a counterparty never seen before | none |
| Unusually large expense (#30) | A debit above the absolute limit, or above a multiple of the vendor or category average | `ANOMALY_LARGE_EXPENSE_ABSOLUTE` (5000.00), `ANOMALY_LARGE_EXPENSE_MULTIPLIER` (3), `ANOMALY_MIN_HISTORY_COUNT` (3), `ANOMALY_BASELINE_DAYS` (90) |
| Category spending increase (#31) | Month-to-date category spend above the baseline by both a percentage and an amount | `ANOMALY_CATEGORY_BASELINE_MONTHS` (3), `ANOMALY_CATEGORY_INCREASE_PERCENT` (50), `ANOMALY_CATEGORY_MIN_INCREASE_AMOUNT` (200.00) |
| Overdue invoice (#36) | An invoice with outstanding > 0 past its due date | `OVERDUE_EVALUATION_INTERVAL_HOURS` (24) |
| Unmatched transaction (#39) | A credit, or a debit to a supplier with bills, still unmatched after N days | `UNMATCHED_AFTER_DAYS` (7), `UNMATCHED_LOOKBACK_DAYS` (60) |
| COGS / margin movement (#42) | COGS growing much faster than revenue, or a margin drop | `PROFIT_COGS_GROWTH_GAP_PERCENT` (20), `PROFIT_MARGIN_DROP_POINTS` (5) |

- Transaction rules only evaluate transactions booked within
  `ANOMALY_EVALUATION_WINDOW_DAYS` (7). Older records are the baseline,
  so the first import of six months of history does not flood the
  queue (#32)
- Limits are exceeded only when the value is strictly greater. Window boundaries are inclusive

Matching thresholds: `MATCH_MIN_SCORE` (50), `MATCH_AMBIGUITY_MARGIN`
(10).

## AI

- AI explains. It never calculates or invents figures: every figure it shows must come from a tool result in the same run
- AI has no write access to financial data, and never accepts matches or changes invoices
