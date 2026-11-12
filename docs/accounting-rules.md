# Accounting rules

The financial conventions LedgerLens follows. The accounting reviewer checks issues and code against this file. If an issue or the code disagrees with it, one of them is wrong. Fix the code, or change this file on purpose and say so in the issue.

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
  reference, description) are never changed after import. Category and
  anomaly flags are stored separately
- Account balance = opening balance + sum of credits - sum of debits
- Periods use the booking date and are inclusive at both ends

## Categories

The fixed list (`backend/ledgerlens/domain/categories.py`):

| Key | Name |
|---|---|
| `revenue` | Revenue |
| `rent` | Rent |
| `software` | Software |
| `utilities` | Utilities |
| `inventory` | Inventory |
| `supplier_other` | Other suppliers |
| `other` | Other |

- A credit can only be `revenue` (or `other`). A debit can only be an
  expense category (or `other`)
- Categories come from rules only. There are no manual corrections in
  the slim scope
- The rules are checked in order and the first match wins. A rule matches
  a transaction of its direction when one of its keywords appears,
  case-insensitively, in the counterparty name or the description, after
  runs of whitespace are collapsed to one space. A transaction that matches no rule gets `other`

## Anomaly rules

Every flag is a potential issue for a person to review. It is never a finding of fraud or error. Thresholds are settings. The defaults below are demo values.

| Rule | Settings (default) |
|---|---|
| Possible duplicate payment (#28) | `ANOMALY_DUPLICATE_WINDOW_DAYS` (3), `ANOMALY_DUPLICATE_AMOUNT_TOLERANCE_PERCENT` (1) |
| Unusually large expense (#30) | `ANOMALY_LARGE_EXPENSE_ABSOLUTE` (5000.00), `ANOMALY_LARGE_EXPENSE_MULTIPLIER` (3), `ANOMALY_MIN_HISTORY_COUNT` (3), `ANOMALY_BASELINE_DAYS` (90) |

Possible duplicate payment (#28, `domain/duplicate_payment.py`): a debit is
flagged when there is an earlier debit, in `(booking_date, id)` order (so a
debit on the same day counts), that:

- has the same counterparty, after the names are trimmed, runs of
  whitespace inside them are collapsed to one space, and they are compared
  case-insensitively
- is at most `ANOMALY_DUPLICATE_WINDOW_DAYS` days earlier
- differs in amount by at most `ANOMALY_DUPLICATE_AMOUNT_TOLERANCE_PERCENT`
  of the larger amount

The flag links the closest earlier match. A debit with no counterparty never
matches.

Unusually large expense (#30, `domain/large_expense.py`): a debit is flagged
when its amount is above `ANOMALY_LARGE_EXPENSE_ABSOLUTE`, or above
`ANOMALY_LARGE_EXPENSE_MULTIPLIER` × its baseline average. The baseline is
the debits booked in the `ANOMALY_BASELINE_DAYS` days before the debit's
booking date; debits on the debit's own day, and the debit itself, are
excluded. It uses the counterparty's debits (names compared as for #28)
when there are at least `ANOMALY_MIN_HISTORY_COUNT` of them. Otherwise, when
the debit has a category, it uses the debits of that category when there
are at least `ANOMALY_MIN_HISTORY_COUNT` of them. Otherwise there is no
average, and only the absolute limit applies.

- The two #30 limits trigger only when the amount is strictly greater. The
  #28 window and tolerance include their bounds
- Evaluation window (#32, `db/repositories/anomalies.py`): the rules flag
  only the debits booked from today − (`ANOMALY_EVALUATION_WINDOW_DAYS` − 1)
  days up to today (default 7 days). Older debits only serve as history, so
  the first import of six months of history does not flood the queue

## Reports

The monthly and expenses reports (#43, `domain/reports.py` and
`db/repositories/reports.py`):

- Months are calendar months of `booking_date`
- `from` and `to` are inclusive, with at most 24 months
- Every account and every transaction status counts
- Money in is the sum of credits, money out the sum of debits, and
  net = in − out, computed from the unrounded sums
- Expenses are debits per category; an uncategorized debit counts as
  `other`
- A month or category with no transactions shows `0.00`
- Each figure is rounded once, at the end
