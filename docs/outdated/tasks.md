# LedgerLens Task Backlog

LedgerLens is a small financial management app for one fictional EUR retail business. It pulls bank transactions from a simulated bank API (DemoBank), stores them in PostgreSQL, flags unusual records, tracks invoices and gross margin, and uses two AI agents (a Financial Analyst and an On-call Responder). The stack is Python/FastAPI, React/TypeScript, PostgreSQL, Docker Compose, OpenTelemetry with Grafana Cloud, and GitHub Actions.

Each task states the context it needs, so it can be handed over on its own. Numbers show a suggested build order only. Money is always a fixed-precision decimal, never a float.

## 1. Empty backend project with a passing test
Goal: Create the backend project skeleton with one passing automated test.
Description: Set up a Python 3.12 project for the backend with dependency management, a linter, a type checker, and pytest. Add a trivial test (for example, a placeholder function) and confirm the test command passes locally. No application logic yet.

## 2. Empty frontend project with a passing test
Goal: Create the frontend project skeleton with one passing automated test.
Description: Set up a React + TypeScript project using Vite, with ESLint, a TypeScript check, and Vitest with Testing Library. Render a placeholder component and add one test that passes. No real pages yet.

## 3. Single command to run all tests
Goal: Provide one documented command that runs lint, type checks, and all tests.
Description: Add a Makefile with `make test` and `make lint` targets that run the backend and frontend checks created in the earlier skeleton tasks. The command must fail if any check fails. Document it in a short section of the README.

## 4. Typed configuration from environment variables
Goal: Load and validate all application settings from environment variables.
Description: Create a settings class for the backend with fields such as database URL, DemoBank URL and API key, sync interval, retry limits, stale threshold, and anomaly thresholds, each with a sensible demo default. Missing required values must fail at startup with a clear message. Add an `.env.example` listing every variable with placeholder values.

## 5. Money and currency helpers
Goal: Provide a tested module for exact decimal money handling.
Description: Write a small module that represents EUR amounts as `Decimal`, rejects floats, rounds to two decimal places with one documented rounding rule, and refuses non-EUR currencies. Cover addition, subtraction, percentages, and rounding edge cases with unit tests.

## 6. Database connection and migrations
Goal: Connect the backend to PostgreSQL and run versioned migrations.
Description: Configure SQLAlchemy 2 and Alembic, a session factory, and a `make migrate` command. Create one trivial initial migration so the process can be verified against a local Postgres. Add a test that applies migrations to an empty database.

## 7. Health endpoint and Docker Compose with database
Goal: Run the backend and PostgreSQL together with one Compose command.
Description: Add a `/api/health` endpoint that reports service status and database connectivity. Write a Dockerfile for the backend and a `docker-compose.yml` with `db` and `backend` services, health checks, and migrations on startup. Verify with `docker compose up --build` and a request to the health endpoint.

## 8. DemoBank service skeleton with authentication
Goal: Create a separate DemoBank service that answers `/health` and enforces an API key.
Description: Build a standalone FastAPI app (its own package, no imports from the LedgerLens backend) with an unauthenticated `/health` and a dependency that requires an `X-API-Key` header on all `/v1/*` routes. Add a Dockerfile and a Compose service, plus tests for authorized and unauthorized requests.

## 9. DemoBank deterministic historical data generator
Goal: Generate about six months of reproducible fictional bank history.
Description: Write a generator with a fixed random seed that produces stable transaction IDs and realistic EUR activity: customer receipts, rent, software subscriptions, inventory purchases, utilities, and supplier payments. Running it twice must yield identical data. Store the output in DemoBank's own tables and test determinism and basic invariants (stable IDs, EUR only, plausible totals).

## 10. DemoBank accounts and balance endpoints
Goal: Expose accounts and current balances over HTTP.
Description: Add `GET /v1/accounts` and `GET /v1/accounts/{id}/balance` to DemoBank, returning data from the generated history. Balance must equal the sum of that account's transactions plus its opening balance. Write tests covering unknown account IDs and the balance calculation.

## 11. DemoBank transactions endpoint with cursor pagination
Goal: Serve transactions with a stable cursor and a limit.
Description: Add `GET /v1/accounts/{id}/transactions?cursor=&limit=` returning transactions ordered by booking date then ID, each with the fields transaction_id, account_id, booking_date, value_date, amount, currency, direction, counterparty name and reference, description, and status. Also add `GET /v1/transactions/{id}`. Test that paging through with a cursor returns every record exactly once, even when new records are appended between calls.

## 12. DemoBank financial anomaly scenarios
Goal: Let a demo operator inject predefined suspicious activity.
Description: Add `POST /admin/scenarios/{name}` for duplicate-looking payment, unusual large expense to a new counterparty, increased category spending, and cash-flow pressure. Each scenario appends deterministic transactions. The admin routes require a separate admin key and are disabled unless an environment flag enables them.

## 13. DemoBank failure, recovery, and reset scenarios
Goal: Simulate an outage and a recovery, and restore the initial state.
Description: Add `timeout`, `server_error`, and `recovery` scenarios that change how `/v1/*` routes respond (delayed response, HTTP 500, then normal). Add `POST /admin/simulation/reset` to return to the deterministic starting dataset. Test each behavior and confirm `/health` stays reachable during a simulated outage.

## 14. DemoBank optional live transaction generation
Goal: Make new transactions appear periodically in demo mode.
Description: Add a configurable background task in DemoBank that appends one ordinary transaction every N seconds when enabled. It must use the same seeded generator style so results stay plausible, and it must be off by default. Test that enabling it adds records and that disabling it stops additions.

## 15. Schema for bank accounts and bank transactions
Goal: Define the tables that store imported bank data.
Description: Create migrations and models for `BankAccount` (provider, external account ID, currency, last cursor, last successful sync) and `BankTransaction` (provider, external transaction ID, dates, `NUMERIC(14,2)` amount, direction, counterparty, reference, category, raw source metadata). Add a unique constraint on provider plus external transaction ID, and a CHECK limiting currency to EUR. Test the constraints directly.

## 16. Schema for import jobs
Goal: Record every synchronization attempt.
Description: Add an `ImportJob` table with account, cursor used, start and end time, status (running, succeeded, succeeded with errors, failed), counts of fetched, created, and skipped records, an error class, and a safe error summary. Add a small repository with functions to start and finish a job. Test the status transitions.

## 17. Bank connector interface and DemoBank connector
Goal: Isolate all DemoBank-specific API details behind one interface.
Description: Define a `BankConnector` protocol with list accounts, get balance, and fetch transactions after a cursor. Implement a DemoBank version using an HTTP client with explicit connect and read timeouts and the API key header, returning provider-neutral objects. Test against a mocked HTTP server for success, timeout, 500, and 401 responses.

## 18. Transaction normalization and validation
Goal: Convert provider records into the internal transaction model safely.
Description: Write a pure function that checks required fields, supported currency, amount format, and direction, and returns either a normalized transaction or a structured rejection reason. Rejecting one malformed record must never raise for the rest of a batch. Unit-test valid records, missing fields, non-EUR currency, and bad amounts.

## 19. Idempotent transaction persistence
Goal: Insert only new transactions and count duplicates.
Description: Write a repository function that inserts a batch using the unique key so existing records are skipped, and returns counts of created and duplicate-skipped rows. Imported fields must never be updated on conflict. Test that inserting the same batch twice creates no extra rows.

## 20. Retry and backoff policy
Goal: Provide a deterministic function for retry delays and limits.
Description: Implement a pure function that, given the attempt number and configuration, returns the next delay (exponential, capped, with optional jitter) or a decision to stop. Authentication and validation error classes must not be retried. Unit-test delays, the attempt limit, and the non-retryable classes without any real sleeping.

## 21. Single synchronization cycle
Goal: Implement one complete fetch, validate, and persist run.
Description: Write a service that reads the account's cursor, fetches pages through the connector, normalizes records, persists them, and records the import job. The cursor and last-success timestamp must update only in the same database transaction as the inserts. Test success, partial validation failure, connector failure, and cursor safety using a fake connector.

## 22. Asynchronous worker loop
Goal: Run synchronization cycles on a schedule with retries.
Description: Build a worker entry point with a plain async loop that runs a cycle every configured interval, applies the retry policy after failures, and shuts down cleanly on a signal. Clock, sleep, and connector must be injectable so tests can drive several cycles instantly with a fake clock. Add a worker service to Docker Compose.

## 23. Transactions list API with filters
Goal: Let the frontend query stored transactions.
Description: Add `GET /api/transactions` with paging, sort order, and filters for date range, category, counterparty, direction, and anomaly status, plus text search on counterparty and reference. Return amounts as strings or decimals, never floats. Test each filter and combinations against seeded rows.

## 24. Accounts, balances, and sync history API
Goal: Expose bank connection status and import history.
Description: Add endpoints that list stored bank accounts with balance and last successful sync, and list import jobs with status and counts. Add a protected demo-only endpoint that triggers a sync immediately. Test the response shapes and the empty state.

## 25. Expense categories and categorization rules
Goal: Assign each transaction a category with deterministic rules.
Description: Create an `ExpenseCategory` table and an ordered rule set matching on counterparty and reference keywords (rent, software, inventory, utilities, revenue, other). Categorization runs on newly imported records, never alters bank fields, and a manual category always wins over a rule. Unit-test rule order and fallback behavior.

## 26. Manual category correction API
Goal: Let a user change a transaction's category.
Description: Add an endpoint to set or clear a manual category on one transaction, recording that the value is user-chosen. The change must not affect any imported bank fields and must be written to an audit event. Test that rule-based recategorization afterward leaves the manual value in place.

## 27. Anomaly storage and listing API
Goal: Provide a common place to store and review flagged records.
Description: Add an `Anomaly` table (type, affected record, rule name, evidence as structured data, severity, status such as open, reviewed, dismissed) and endpoints to list, view, and change the status of anomalies. Wording in responses must say "potential issue", not fraud. Test status changes and that evidence is returned intact.

## 28. Possible duplicate payment rule
Goal: Flag payments that look like duplicates.
Description: Write a pure rule that flags two outgoing transactions to the same counterparty with the same or nearly the same amount within a configurable number of days, optionally comparing references. Store the two transaction IDs and the matching reasons as evidence. Unit-test exact duplicates, near duplicates, outside-window cases, and different counterparties.

## 29. Unfamiliar counterparty rule
Goal: Flag the first transaction with a counterparty never seen before.
Description: Write a rule that flags a transaction when no earlier transaction exists with the same normalized counterparty name. Include the earliest comparison date and the count of prior transactions as evidence. Unit-test new and known counterparties and name normalization differences such as casing and spacing.

## 30. Unusually large expense rule
Goal: Flag expenses far above normal for their vendor or category.
Description: Write a rule that flags an outgoing transaction exceeding a configurable absolute threshold, or a configurable multiple of the historical average for that vendor or category. Include the compared figures in the evidence. Handle cases with too little history by falling back to the absolute threshold only, and unit-test them.

## 31. Category spending increase rule
Goal: Flag a category whose current spending is well above its baseline.
Description: Write a rule that compares current-period spending in each category with the average of previous periods and flags increases above a configurable percentage and minimum amount. Evidence must include current total, baseline, and the periods used. Unit-test normal variation, a spike, and a category with no history.

## 32. Run anomaly rules after each import
Goal: Evaluate all rules automatically on newly imported transactions.
Description: After a successful sync commit, run the available transaction rules on the new records only, create anomalies without duplicating existing ones for the same record and rule, and count alerts created. A failure in a rule must not roll back the imported transactions. Test with a fake batch that triggers several rules, and with repeated runs.

## 33. Invoice schema and API for payables and receivables
Goal: Store supplier bills and customer invoices and let a user manage them.
Description: Create tables and endpoints to create, edit, list, and view invoices with a type (payable or receivable), counterparty, invoice number, issue date, due date, total, amount paid, and computed outstanding. Enforce paid between 0 and total and keep outstanding consistent. Test validation errors and the outstanding calculation.

## 34. Aging and overdue calculation
Goal: Compute overdue status and aging buckets for invoices.
Description: Write a pure function using one documented convention: days overdue from the due date, with buckets current, 1–30, 31–60, 61–90, and over 90, counting only invoices with an outstanding amount greater than zero. The evaluation date is a parameter. Unit-test boundary days, fully paid invoices, and invoices due today.

## 35. Payables and receivables summary reports
Goal: Provide totals and aging for AP and AR.
Description: Add report endpoints returning total outstanding, total overdue, bucket totals, and upcoming due dates for payables and for receivables. Calculations use the aging function and exact decimals. Test with seeded invoices whose totals are known in advance.

## 36. Overdue invoice alert rule
Goal: Create an anomaly for each overdue invoice.
Description: Add a rule that raises one open anomaly per overdue invoice, updating its evidence (days overdue, outstanding) as time passes and closing it when the invoice is fully paid. It runs on a daily or on-demand basis. Test creation, update without duplication, and automatic closure.

## 37. Reconciliation candidate scoring
Goal: Suggest which invoice a bank transaction pays.
Description: Write a pure function that scores a transaction against open invoices using amount, direction, date proximity to the due date, counterparty name similarity, and invoice number appearing in the reference. Return a score and a list of human-readable reasons. Unit-test exact matches, partial payments, ambiguous cases with two close candidates, and no match.

## 38. Match suggestions and review API
Goal: Let a user accept, reject, or manually pick a match.
Description: Add a `TransactionMatch` table and endpoints to generate suggestions, list the review queue, accept, reject, or manually assign a match. Only accepting changes the invoice's paid and outstanding amounts, in a single database transaction with an audit event. Ambiguous or low-score suggestions stay in the queue; test that accepting updates the invoice correctly and rejecting changes nothing.

## 39. Unmatched transaction rule
Goal: Flag transactions that remain unmatched.
Description: Add a rule that flags incoming or invoice-related outgoing transactions still unmatched after a configurable number of days, and counts them for a metric. Evidence lists the best rejected candidates if any. Unit-test timing thresholds and transactions that become matched later.

## 40. Inventory, purchase, and sales record storage
Goal: Store the monthly data needed for COGS.
Description: Add tables and endpoints for monthly inventory snapshots (opening and closing value), inventory purchases (date, supplier, amount, whether it counts toward inventory), and monthly revenue. All amounts are exact decimals in EUR. Test creation, listing by month, and validation such as negative values.

## 41. COGS, gross profit, and gross margin calculation
Goal: Compute monthly profitability with exact arithmetic.
Description: Write pure functions for COGS = opening inventory + purchases − closing inventory, gross profit = revenue − COGS, and gross margin percent, with an explicit result for zero revenue instead of an error. Document the simplified periodic-inventory assumption. Unit-test normal months, zero revenue, negative gross profit, and rounding.

## 42. Profitability report API and movement rule
Goal: Report profitability by month and flag material changes.
Description: Add an endpoint returning revenue, purchases, COGS, gross profit, and gross margin per month with change from the prior month. Add a rule that flags COGS growing much faster than revenue or a margin drop above a configurable threshold. Test with seeded months where the expected figures are computed by hand.

## 43. Overview and expenses report endpoints
Goal: Provide the totals needed by the dashboard.
Description: Add endpoints returning cash balance, revenue and expense totals for a period, AP and AR totals, open alert counts, and latest sync status, plus spending by category and by counterparty over time with a previous-period comparison. All figures come from database queries and the calculation modules. Test against a small known dataset.

## 44. LedgerLens demo seed data
Goal: Load reproducible fictional invoices, inventory, and sales on first start.
Description: Write an idempotent seed command that inserts demo counterparties, supplier and customer invoices with a spread of due dates and statuses, six months of inventory snapshots, purchases, and revenue, labeled as demo data. Running it twice must not duplicate anything. Add a `make seed` target and a test that checks the resulting counts and totals.

## 45. Frontend app shell, routing, and API client
Goal: Build the navigation frame and typed API layer.
Description: Create the layout with navigation for the nine pages (Overview, Transactions, Reconciliation, Expenses, Receivables, Payables, Profitability, Insights & Alerts, Data Sources) as placeholder routes, and a persistent banner stating the data comes from a simulated bank. Generate API types from the backend OpenAPI schema and set up TanStack Query. Test that each route renders and the banner appears.

## 46. Data Sources page
Goal: Show bank connection status and synchronization history.
Description: Build the page listing accounts with balances, last successful sync, and a table of import jobs with status and counts. In demo mode, show buttons to run a sync now and to trigger DemoBank scenarios. Test loading, empty, and error states with a mocked API.

## 47. Transactions page
Goal: Let users browse, filter, and categorize transactions.
Description: Build a table of transactions with filters for date, category, counterparty, and anomaly status, text search, paging, and a control to change a category manually. Show an anomaly badge that links to its evidence. Test filtering, searching, and the category change using a mocked API.

## 48. Overview page
Goal: Give a one-screen summary of the business position.
Description: Build cards for cash balance, revenue, expenses, AP outstanding, AR outstanding, open alerts, and last sync status, plus a simple trend chart. Values come only from the report endpoints. Test that the numbers render exactly as returned, including large and negative values.

## 49. Payables and Receivables pages
Goal: Manage invoices and show aging.
Description: Build two pages (sharing components) listing invoices with outstanding and overdue indicators, an aging summary, and forms to create and edit an invoice with validation. Test form validation, the aging display, and the outstanding balance shown for partial payments.

## 50. Reconciliation page
Goal: Let a user review suggested matches.
Description: Build a review queue showing each transaction, the suggested invoice, the score, and the reasons, with accept, reject, and manual-select actions. Ambiguous items must be visibly marked and never auto-accepted. Test accepting, rejecting, and the manual selection flow with a mocked API.

## 51. Expenses page
Goal: Visualize spending by category and counterparty.
Description: Build charts and tables of spending by category and vendor over time with a comparison to the previous period and highlighted unusual changes. Test that the period comparison and highlights render from the API data.

## 52. Profitability page
Goal: Show revenue, COGS, gross profit, and margin by month.
Description: Build a monthly table and chart, a form for entering inventory snapshots, purchases, and revenue, and an explanation of the simplified COGS formula. Handle the zero-revenue case in the display. Test the figures, the form, and the zero-revenue message.

## 53. Insights and Alerts page
Goal: List anomalies, alerts, and incidents with their evidence.
Description: Build the page with tabs for financial anomalies, operational alerts, and incidents. Selecting an anomaly shows its rule, evidence, and status controls, and wording says "potential issue". Test opening an anomaly, changing its status, and showing an incident with its recovery state.

## 54. Alert and incident schema with sync watchdog
Goal: Detect sustained sync failure or a stale feed and open an incident.
Description: Add `Alert` and `Incident` tables and a watchdog function that, from import job history, raises an alert when three consecutive jobs fail or the last success is older than a configurable threshold, without creating duplicates for an already-open alert. Add endpoints to list alerts and incidents. Unit-test both triggers, recovery closing, and duplicate suppression using an injected clock.

## 55. Financial Analyst agent tools
Goal: Define the read-only data tools the analyst agent may call.
Description: Implement tool functions that return minimal, already-computed data: one transaction, one anomaly, transactions for a counterparty, a category summary, one invoice, and a profitability month. Each tool has a typed input and output schema, performs no writes, and omits credentials and raw provider metadata. Test the outputs and that no write capability is exposed.

## 56. Financial Analyst agent and investigation endpoint
Goal: Explain an anomaly using retrieved records and computed figures.
Description: Build a tool-calling loop with the Anthropic SDK that investigates a chosen anomaly and returns a structured result: summary, evidence entries (record type, ID, figure, source tool), confidence, uncertainties, and a human-review flag. Reject any output that fails the schema or cites a figure no tool returned. Test with a stubbed model client, and make the endpoint return a clear message when no API key is configured.

## 57. Investigation panel in the frontend
Goal: Let a user ask the analyst to investigate an anomaly and see the result.
Description: Add an "Investigate" action on the anomaly view that calls the investigation endpoint and shows the summary, evidence with record links, confidence, and uncertainties, plus a notice that the output is an AI-assisted explanation for human review. Handle loading, failure, and not-configured states. Test each state with a mocked API.

## 58. Responder policy guard
Goal: Enforce hard limits on any automated recovery action.
Description: Write deterministic code deciding whether a retry or requeue is allowed: at most three agent-initiated actions per incident, exponential spacing between them, no retries for authentication or validation failures, and only one action in flight. The guard sits between the agent and the tools and cannot be overridden by model output. Unit-test every rule with a fake clock.

## 59. On-call Responder agent
Goal: Diagnose a sync incident and attempt a permitted recovery.
Description: Implement a tool-calling agent that reads recent import jobs and a summary of sync metrics, classifies the problem (timeout, server error, configuration, malformed data, persistent outage), and may call only `retry_sync_job` or `requeue_failed_job` through the policy guard. It returns a structured diagnosis and action list. Test with a stubbed model and a fake sync service, including a case where the guard refuses an action.

## 60. Incident verification and history
Goal: Mark an incident recovered only after confirmed recovery.
Description: After a responder action, check that a later import job succeeded and the last-success time advanced, then record the diagnosis, actions, and outcome on the incident. If verification fails, keep the incident open and flag it for a human. Test the recovered path, the still-failing path, and that history is stored in order.

## 61. OpenTelemetry setup for traces
Goal: Emit traces from all services with context propagated between them.
Description: Configure the OpenTelemetry SDK in the backend, worker, and DemoBank with FastAPI, HTTP client, and database instrumentation, and create a root span for each sync cycle with child spans for fetch, normalize, persist, and analysis. Trace context must flow from the worker into DemoBank. Verify with an in-memory span exporter in a test.

## 62. Application metrics
Goal: Record the metrics needed for sync health and alerting.
Description: Define counters, a histogram, and a last-success gauge for sync success and failure, duration, records fetched, created, and duplicate-skipped, unmatched transactions, reconciliations, and alerts created. Labels may only be low-cardinality values like outcome and error class. Test that a successful and a failing cycle update the expected metrics.

## 63. Structured logging with trace IDs and redaction
Goal: Produce JSON logs that link to traces and never contain sensitive fields.
Description: Configure JSON logging that adds trace and span IDs to every record and removes or masks a denylist of keys (counterparty name, description, reference, account identifiers, API keys, authorization headers). Test that marker strings placed in sensitive fields never appear in captured log output.

## 64. OpenTelemetry Collector with Grafana Cloud export
Goal: Forward telemetry through a Collector to Grafana Cloud.
Description: Add an `otel-collector` Compose service with a configuration that receives OTLP, applies memory limiting, attribute redaction, and batching, and exports metrics, logs, and traces to Grafana Cloud using credentials from environment variables. If the credentials are empty, fall back to a console exporter so the stack still starts. Document how to obtain and set the credentials.

## 65. Grafana dashboards and alert rules
Goal: Provide viewable dashboards and alerts for sync health.
Description: Create dashboards for bank sync health (success and failure rate, duration, time since last success, record counts) and API latency and errors, and alert rules for repeated failures and a stale feed. Store them as exported files under `observability/` and write a short guide showing how to view a trace from a failed sync and its correlated logs.

## 66. Telemetry privacy test
Goal: Prove that sensitive financial content does not reach telemetry.
Description: Add an automated test that runs a sync using records containing recognizable marker strings in counterparty, description, and reference fields, and asserts none appear in captured spans, metric labels, or logs. Also assert that the API key never appears. Run it as part of the standard test command.

## 67. Integration test for sync and idempotency
Goal: Verify the real DemoBank-to-database path end to end.
Description: Write an integration test that starts a DemoBank instance and a test PostgreSQL database, runs a sync, checks that transactions were stored, runs it again, and checks that the row count is unchanged. It also confirms the data survives a new database session. Make it runnable locally and in CI.

## 68. Integration test for failure, alert, and recovery
Goal: Verify the outage-to-recovery workflow automatically.
Description: Write an integration test that triggers DemoBank's failure scenario, runs enough sync cycles to record failed jobs, checks that the watchdog opens an alert and incident, restores DemoBank, runs the responder with a stubbed model, and confirms the incident closes only after a successful sync. Use fake time to avoid real waiting.

## 69. Full stack in Docker Compose
Goal: Start every service with one command.
Description: Complete `docker-compose.yml` with frontend, backend, worker, DemoBank, database, and collector services, health-check-based start order, automatic migrations and seeding in demo mode, and documented local URLs. Verify from a clean checkout with `docker compose up --build` and write the verification steps in the README.

## 70. Pull request CI workflow
Goal: Run all checks automatically on every pull request.
Description: Add a GitHub Actions workflow that runs backend lint and type checks, unit tests, frontend lint, type check and tests, integration tests with a Postgres service, and a Docker image build. Cache dependencies, and fail the workflow on any step failure. Document the required status checks.

## 71. Image build and automatic staging deployment
Goal: Deploy every merge to main to a staging environment.
Description: Add a workflow that builds versioned images tagged with the commit SHA, pushes them to a container registry, and deploys them to a staging environment on the chosen hosting platform, with secrets kept in the platform and repository secret stores. Staging must have DemoBank admin controls disabled by default. Record the staging URL in the README.

## 72. Manual production deployment and rollback
Goal: Promote a tested image to production only after approval, and support rollback.
Description: Add a manually triggered workflow protected by a required-reviewer environment that deploys an existing image tag to production, keeping prior tags available. Write a runbook section with exact rollback steps and note that database migrations must stay backward compatible for one release. Demonstrate a rollback and record the result.

## 73. Project documentation: README and AGENTS.md
Goal: Make the repository understandable to reviewers and coding agents.
Description: Write a README covering the problem, features, architecture overview, one-command setup, local URLs, demo data, test command, deployment, and limitations. Write a concise root `AGENTS.md` pointing to the detailed documents in `docs/`, listing the main commands and the project rules (exact decimals, no AI-calculated figures, no AI write access to financial data).

## 74. Accounting rules and runbook documentation
Goal: Document the formulas, thresholds, and operational procedures.
Description: Write `docs/accounting-rules.md` with the aging convention, outstanding formula, COGS and margin formulas, rounding rule, and every anomaly rule with its configurable thresholds. Write `docs/runbook.md` covering the sync-failure alert, the responder's allowed actions and limits, manual recovery steps, and rollback. Cross-check each rule description against the implemented behavior.

## 75. Final end-to-end demo verification
Goal: Confirm the full reviewer walkthrough works from a clean start.
Description: From a fresh clone, follow the demo script: start the stack, observe a sync, repeat it without duplicates, trigger an anomaly scenario and see it flagged and explained, view AP, AR, matching, and profitability, trigger an outage, see the alert and traces, and see the responder recover it. Fix or log any gaps found and record the outcome with screenshots in the repository.
