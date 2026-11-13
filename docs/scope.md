# Scope

LedgerLens syncs a business bank account into its own database and
analyses the transactions in two ways:

1. **Spending by category:** rules put every transaction in a category.
   The Overview and Expenses pages show the balance, money in and out per
   month, and spending per category and month.
2. **Anomaly detection:** after each sync, two rules flag transactions
   for a person to review: possible duplicate payments and unusually large
   expenses. A flag is a potential issue, never a finding of fraud.

The bank is DemoBank, a simulated bank with fictional data. It plants one
duplicate payment and one unusually large expense, so the demo always has
something to find.

## What is built

| Part | What it does | Issues |
|---|---|---|
| DemoBank | Simulated bank: a fixed six-month history, accounts, balances and paged transactions behind an API key, plus the two planted anomalies | #8–#12 |
| Sync | Fetches accounts and transactions on demand (`POST /api/sync` or a CLI command), validates them, stores them once and records the last sync result | #15, #17–#19, #21 |
| Categories and reports | Rule-based categories, monthly money in and out, spending per category and month | #25, #43 |
| Anomaly detection | Duplicate payment and large expense rules, run after every sync; flags can be listed and marked reviewed | #27, #28, #30, #32 |
| API | Accounts, transactions with filters, categories, reports and anomalies | #23, #24 |
| Frontend | Overview, Transactions, Expenses and Alerts pages | #45, #47, #48, #51, #53, #105, #115 |
| Observability | Traces, metrics and JSON logs of the sync, sharing one trace ID across backend and DemoBank, viewable in the local Grafana (otel-lgtm), the provisioned alert rule "LedgerLens sync failing" and the provisioned home dashboard "LedgerLens sync" | #122, #123, #126 |
| Delivery | The full stack starts with `docker compose up --build`; docs; end-to-end checks | #69, #73, #75, #80 |

Each issue on GitHub holds its acceptance criteria and the PM, engineer and
QA comments. The original plan was larger: the issues for features that
were not built are closed as "not planned".

## How it fits together

DemoBank → sync (connector, validation, storage, categories, anomaly
rules) → PostgreSQL → API → frontend.

The backend and DemoBank send traces, metrics and logs over OTLP to the
`otel-lgtm` container (Grafana on port 3000), whose home page is the
"LedgerLens sync" dashboard and where an alert rule fires when a sync
fails.

The financial rules (money, categories, the two anomaly rules and the
reports) are in [`accounting-rules.md`](accounting-rules.md). How the work
is organised is in [`process.md`](process.md).
