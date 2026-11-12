# Scope

LedgerLens syncs a business bank account from DemoBank, a simulated bank,
into its own database. It then analyses the transactions in two ways:

1. **Spending by category**: rules put each transaction in a category.
   The overview and expenses pages show balance and spending per category
   and month
2. **Anomaly detection**: after each sync, two rules flag transactions for
   a person to review. They are possible duplicate payments and unusually
   large expenses

This file replaces `docs/outdated/` as the reference for scope. The scope
was cut on 2026-11-12 to fit the remaining time. Everything not listed
here is out of scope. The issues that covered it are closed as "not
planned".

## Kept issues

| Area | Issues |
|---|---|
| DemoBank | #9 history generator (done), #10 accounts and balances, #11 transactions with cursor pagination, #12 anomaly scenarios |
| Sync pipeline | #15 schema, #17 connector, #18 normalization and validation, #19 idempotent persistence, #21 sync cycle |
| API | #23 transactions list, #24 accounts and balances |
| Spending by category | #25 categories and rules, #43 overview and expenses reports |
| Anomaly detection | #27 anomaly storage and listing, #28 possible duplicate payment, #30 unusually large expense, #32 run the rules after each sync |
| Frontend | #45 app shell, #47 transactions, #48 overview, #51 expenses, #53 alerts |
| Delivery | #69 full stack in Compose, #73 documentation, #80 MVP gate, #75 final demo check |

## How the kept issues are slimmed

The PM trims each issue to this list when grooming it. These are the
rules:

- **#12:** plants only the anomalies the two rules detect: one duplicate
  payment and one unusually large expense
- **#21:** sync runs on demand, through a backend endpoint or a CLI
  command. There is no background worker (#22), no retry or backoff
  policy (#20) and no import-job table (#16). A failed sync reports its
  error and can be run again
- **#24:** accounts and balances. Sync history is reduced to the last
  sync time and result
- **#25:** a fixed category list and simple matching rules. There are no
  manual corrections (#26)
- **#27:** stores and lists flags. A simple "reviewed" status is enough
- **#43:** overview (balance, money in and out per month) and expenses
  per category and month
- **#45:** no login. Backend authentication (#76) is out of scope
- **#53:** lists anomaly flags only. There are no incidents or agents
- **#69:** `db`, `backend`, `demobank` and `frontend`. No telemetry stack
- **#75 and #80:** verify the slim scope end to end, nothing more

## Out of scope

- Invoices, payables and receivables, aging and overdue alerts (#33–#36)
- Reconciliation and match suggestions, unmatched transactions
  (#37–#39, #50)
- Inventory, COGS and profitability (#40–#42, #52)
- Unfamiliar counterparty and category increase rules (#29, #31)
- AI agents, investigations and responders (#55–#60, #78, #79)
- Telemetry, metrics, dashboards and alerting (#54, #61–#66)
- Integration test suites, CI and deployment (#67, #68, #70–#72)
- DemoBank failure and live scenarios (#13, #14), and its scenario proxy (#77)
- Data sources page (#46), demo seed data (#44), accounting rules
  documentation (#74)

## Build order

Issue numbers give the order. The vertical slice comes first: build #10
to #24 together with #45, #47, #48 and #69. Next is the MVP gate (#80),
DemoBank → sync → database → dashboard. After that come the two
analyses (#25, #43, #51, then #27, #28, #30, #32, #53), and last #73
and #75.
