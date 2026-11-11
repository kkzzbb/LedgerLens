# LedgerLens — AI-Powered Financial Management & Accounting Intelligence

> **Project type:** AI Dev Tools course final project  
> **Working product:** LedgerLens  
> **Data provider:** DemoBank API (a simulated bank API built specifically for this project)  
> **Target user:** A small retail/e-commerce business owner, bookkeeper, or accountant  
> **Target effort:** Approximately 20 hours for the course MVP  
> **Primary currency:** EUR  
> **Initial scope:** One fictional business, one DemoBank connection, and a deliberately limited accounting workflow

## 1. Project summary

LedgerLens is a lightweight financial operations platform for a small business. It automatically retrieves bank transactions from a simulated bank API, stores and normalizes them, combines them with invoice and inventory records, and presents useful financial analysis.

The application helps a business answer questions such as:

- What money came in and went out of the business?
- Which expenses increased unusually?
- Does a payment appear to be duplicated?
- Which customer invoices are overdue, and how much is still outstanding?
- How much does the business owe suppliers?
- Which bank transactions have not been matched to invoices?
- How have revenue, cost of goods sold (COGS), gross profit, and gross margin changed?
- Has the financial data feed stopped updating or started failing?

LedgerLens combines deterministic accounting calculations and anomaly rules with AI-assisted investigation and explanation. The AI must use actual records and computed results; it must not invent financial figures or make autonomous payment or bookkeeping decisions.

### Product positioning

**LedgerLens — Know where your money goes. Understand what you owe. Detect what doesn't look right.**

This is not intended to be a complete accounting or bookkeeping system. It is a small financial data management and analysis product that demonstrates an automated data pipeline, useful accounting workflows, AI-assisted investigation, production monitoring, and incident response.

## 2. The problem

Small businesses often keep financial information in separate systems:

- Bank accounts contain payment and receipt transactions.
- Supplier invoices represent accounts payable (AP).
- Customer invoices represent accounts receivable (AR).
- Purchase and inventory records are needed to calculate COGS.
- Sales records provide revenue information.

A business owner or accountant has to combine this information to understand cash movement, outstanding liabilities, overdue receivables, spending trends, and profitability. Important issues can be missed, such as duplicate-looking payments, unusually high expenses, overdue invoices, unmatched payments, or a financial data feed that has stopped updating.

LedgerLens brings a small, well-defined subset of this information together and highlights records that deserve human attention.

## 3. Core product workflow

The main end-to-end workflow is:

1. LedgerLens connects to the **DemoBank API** using configured sandbox credentials/API key.
2. A background worker periodically requests account and transaction data.
3. The worker validates and normalizes the returned records.
4. New transactions are stored in PostgreSQL without duplicating previously imported transactions.
5. Transactions are categorized and checked against deterministic anomaly rules.
6. Bank payments and receipts can be matched to supplier and customer invoices.
7. The application calculates expense summaries, AP/AR aging, and simple profitability metrics.
8. Financial alerts are created for unusual or overdue records.
9. A Financial Analyst Agent investigates selected anomalies and explains the evidence.
10. Separately, an operational alert fires if bank synchronization fails or becomes stale. An On-call Responder Agent investigates, attempts a permitted recovery, and verifies whether synchronization has resumed.

**Important distinction:** A suspicious financial transaction is a business alert. A failed or stale synchronization pipeline is a software/operations incident. They use different detection rules and different response workflows.

## 4. Data sources and automation strategy

### 4.1 DemoBank API is the primary bank data source

The MVP will use a small simulated bank service called **DemoBank**. DemoBank is an HTTP API that behaves like an external bank data provider from LedgerLens' perspective. It exposes accounts, balances, and transactions.

DemoBank is not a real bank and does not connect to personal bank accounts. Its purpose is to make the integration workflow automated, reproducible, testable, and independent of real-bank access or credentials.

LedgerLens must communicate with DemoBank through a bank-connector interface. The accounting and analysis code should not depend directly on DemoBank-specific response formats. This leaves a future path to replace the simulated provider with a real Open Banking provider without rewriting the accounting logic.

### 4.2 Suggested DemoBank API endpoints

The exact route names can be finalized during implementation, but the proposed API is:

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/health` | Health check for DemoBank |
| `GET` | `/v1/accounts` | List available bank accounts |
| `GET` | `/v1/accounts/{account_id}/balance` | Retrieve current account balance |
| `GET` | `/v1/accounts/{account_id}/transactions` | Retrieve transactions, optionally filtered by date/cursor |
| `GET` | `/v1/transactions/{transaction_id}` | Retrieve one transaction, if needed |
| `POST` | `/admin/scenarios/{scenario_name}` | Trigger a predefined simulation scenario in local/demo environments only |
| `POST` | `/admin/simulation/reset` | Reset the simulation to its deterministic initial state |

The transaction endpoint should support pagination or a stable cursor and a `since`/updated-after filter. The response should include stable external transaction IDs so LedgerLens can safely synchronize only new records.

Suggested transaction fields:

- `transaction_id` (stable provider-side ID)
- `account_id`
- `booking_date`
- `value_date` (optional)
- `amount`
- `currency` (EUR in the MVP)
- `direction` (debit/credit) or a consistently signed amount
- `counterparty_name`
- `counterparty_account_reference` (synthetic only)
- `description` or payment reference (synthetic only)
- `status`

Do not include real personal or bank information in the simulator.

### 4.3 How DemoBank creates its data

Do not ask an LLM to generate random bank CSV files. Use a deterministic Python seed/generator script and predefined scenarios.

The generator should:

- Create approximately six months of fictional historical transactions so the application has a baseline for trend and anomaly analysis.
- Generate normal business activity such as customer receipts, rent, software subscriptions, inventory purchases, utilities, and supplier payments.
- Use stable IDs and a fixed random seed so the same initial dataset can be reproduced.
- Optionally create a new transaction every few minutes in local demo mode to make automatic synchronization visible.
- Provide scenario controls for repeatable demonstrations and tests.

Suggested scenarios:

| Scenario | What it demonstrates |
|---|---|
| Normal activity | Ordinary receipts, supplier payments, rent, and recurring expenses |
| Duplicate-looking payment | Two similar or identical payments to the same supplier |
| Unusual expense | A large payment to a new or unfamiliar counterparty |
| Increased category spending | A category such as software or utilities rises materially compared with its baseline |
| Cash-flow pressure | Several larger supplier payments occur close together |
| API timeout/failure | DemoBank responds with a timeout or server error so the responder can be tested |
| Recovery | DemoBank resumes normal responses so the recovery can be verified |

Scenario controls should be restricted to local/demo use and must not be exposed as public production controls.

### 4.4 Synchronization behavior

For local demonstration, a synchronization interval of approximately two minutes is useful because a reviewer can see new data arrive. This is a demo setting, not a claim about real-bank polling rules. A future real provider's consent, rate limits, and API requirements must determine its production schedule.

The worker should:

1. Read the last successful synchronization cursor/timestamp for the account.
2. Request records after that cursor from DemoBank.
3. Validate required fields and supported currency.
4. Normalize the provider response into LedgerLens' internal transaction model.
5. Insert new transactions using an idempotency constraint.
6. Record the import job result and update `last_successful_sync_at` only after a successful commit.
7. Trigger categorization and analysis for newly imported records.

A database uniqueness constraint such as `(provider, external_transaction_id)` should prevent duplicates. Re-running the same synchronization must not create extra transactions.

### 4.5 Other financial records

Bank transactions alone are not sufficient to calculate AP, AR, or COGS. The MVP should also support:

- Supplier bills and customer invoices entered through simple forms and/or seeded demo records.
- Basic sales/revenue records or a small sales summary.
- Monthly opening and closing inventory values, plus purchases during the period.

These records can be entered within LedgerLens or loaded using deterministic seed data. Do not make a second external accounting integration a requirement for the 20-hour MVP.

CSV import can remain an optional future convenience, but it is not the main user journey and is not required for the demo.

## 5. Main application features

### 5.1 Bank connection and transaction management

- Connect to the local DemoBank service using a configured API key/token.
- Display available demo accounts and current balances.
- Synchronize transactions automatically in the background.
- Display transaction date, counterparty, description/reference, amount, direction, and category.
- Filter/search transactions by date, category, counterparty, and anomaly status.
- Track synchronization history and errors.
- Prevent duplicate imports.

### 5.2 Expense management and anomaly detection

- Assign transactions to a simple expense/revenue category.
- Start with deterministic rules and allow manual category correction.
- Show spending by category and counterparty over time.
- Flag possible duplicate payments.
- Flag unfamiliar counterparties or unusually high transactions.
- Flag spending increases compared with a historical baseline.
- Explain why a record was flagged and expose the underlying evidence.

A flag means **potential issue requiring review**, not confirmed fraud. Rules should have configurable thresholds and should avoid overclaiming.

### 5.3 Accounts Payable (AP)

AP represents amounts the business owes suppliers.

MVP capabilities:

- Create and edit supplier bills.
- Store supplier, invoice number, invoice date, due date, total amount, amount paid, and outstanding amount.
- Display total outstanding supplier liabilities.
- Identify overdue bills and upcoming due dates.
- Show aging categories (for example, current/0–30, 31–60, 61–90, and 90+ days overdue).
- Match an outgoing bank transaction to a supplier bill.
- Flag potential duplicate supplier payments.

### 5.4 Accounts Receivable (AR)

AR represents amounts customers owe the business.

MVP capabilities:

- Create and edit customer invoices.
- Store customer, invoice number, invoice date, due date, total amount, amount received, and outstanding amount.
- Display total outstanding customer balances.
- Identify overdue receivables and aging categories.
- Match incoming bank transactions to customer invoices.
- Show unmatched incoming payments for human review.

### 5.5 Transaction reconciliation

- Suggest a match based on amount, direction, date proximity, counterparty, and reference.
- Show the reasons and confidence/evidence for a suggested match.
- Allow a user to accept, reject, or manually select a match.
- Keep uncertain matches in a review queue.
- Do not silently mark ambiguous records as reconciled.

### 5.6 COGS and profitability

COGS is the cost of inventory actually sold during a period. It cannot be accurately inferred from bank payments alone. The MVP therefore uses purchase records and monthly inventory snapshots.

Formula:

`COGS = Opening Inventory + Purchases - Closing Inventory`

`Gross Profit = Revenue - COGS`

`Gross Margin (%) = (Gross Profit / Revenue) * 100`

For the MVP:

- Store monthly opening and closing inventory values.
- Store purchases relevant to inventory.
- Store or seed a simple monthly revenue figure.
- Calculate COGS, gross profit, and gross margin deterministically.
- Compare periods and flag material changes, such as COGS rising much faster than revenue.

This is a simplified management-accounting calculation, not a complete inventory valuation or statutory accounting implementation.

### 5.7 Dashboard and insights

Proposed navigation:

| Page | Content |
|---|---|
| Overview | Cash position, revenue, expenses, AP, AR, alerts, recent synchronization status |
| Transactions | Imported bank transactions, categories, filters, anomaly flags |
| Reconciliation | Suggested and confirmed invoice/payment matches |
| Expenses | Spending by category/vendor and unusual changes |
| Receivables | Customer invoices, outstanding balances, aging |
| Payables | Supplier bills, outstanding balances, aging |
| Profitability | Revenue, COGS, gross profit, gross margin |
| Insights & Alerts | AI investigation results, financial alerts, operational incidents |
| Data Sources | DemoBank connection and synchronization history |

All displayed amounts must come from database records and deterministic calculations. Seed data may be used for the demonstration, but label it clearly as demo data.

## 6. AI agents and their responsibilities

There are two distinct groups of agents in this project: development agents that help build the product, and runtime agents that operate inside the finished product.

### 6.1 Development agent team

| Agent/role | Responsibility |
|---|---|
| Product Agent | Maintains product requirements, acceptance criteria, and GitHub tasks |
| Backend Agent | Implements API endpoints, data models, synchronization, and accounting services |
| Frontend Agent | Implements dashboard pages and user workflows |
| QA Agent | Creates/runs unit, integration, and frontend tests and checks acceptance criteria |
| SRE/Infrastructure Agent | Reviews telemetry, deployment, reliability, and runbooks |

The development workflow should be documented and evidenced through the public issue tracker and pull requests. Agents should work on small, explicitly scoped tasks rather than making broad, unreviewed changes.

### 6.2 Runtime agents

For the MVP, keep the runtime agent team small:

**Financial Analyst / Transaction Investigation Agent**

- Receives a selected anomaly or financial question.
- Retrieves relevant transaction, invoice, category, and historical summary records through read-only tools.
- Uses deterministic service results as the source of financial figures.
- Explains why a transaction or trend was flagged.
- Provides record IDs and supporting evidence in its structured response.
- Labels uncertainty and asks for human review where appropriate.

**On-call Responder Agent**

- Wakes when an operational alert is triggered by failed or stale bank synchronization.
- Retrieves relevant structured logs, metrics, traces, import-job history, and error details.
- Identifies likely causes such as timeout, temporary server error, invalid configuration, or data validation failure.
- Executes only predefined, permission-controlled actions such as a bounded retry or re-queuing a failed import job.
- Verifies whether synchronization has recovered.
- Records its investigation, action, and outcome in an incident history.

The Financial Analyst handles business/financial anomalies. The On-call Responder handles application reliability incidents. They should not be confused.

### 6.3 Agent safety and authority

- Agents must not initiate bank payments or transfer money.
- Agents must not autonomously alter invoice amounts or confirm ambiguous reconciliations.
- Accounting calculations must be performed by deterministic application services.
- Financial agents should have read-only access to financial records for investigation.
- The responder should have a narrow allowlist of operational tools, such as retrying a failed synchronization job.
- Retry actions must be bounded and use backoff to avoid request storms.
- Sensitive financial data should be minimized in prompts and logs.
- AI output should be validated against a structured schema before being shown or stored.
- Human review is required for material or uncertain financial decisions.

## 7. Suggested technical architecture

### 7.1 Technology stack

| Area | Proposed technology | Reason |
|---|---|---|
| Frontend | React + TypeScript | Interactive dashboard and testable UI |
| Backend API | Python + FastAPI | Clear REST API, validation, and Python ecosystem |
| DemoBank | Small FastAPI service | Separate simulated external provider |
| Database | PostgreSQL | Persistent relational financial records |
| Background processing | Python worker with a simple scheduler/job loop | Automatic synchronization and retry workflow |
| AI | LLM API with structured tool calls | Financial explanations and incident investigation |
| Observability | OpenTelemetry | Correlated traces, metrics, and logs |
| Local environment | Docker Compose | One-command startup, including database and DemoBank |
| CI/CD | GitHub Actions | Automated tests and deployment workflow |

Keep the architecture small. Do not introduce a message broker, microservice framework, or multi-agent orchestration platform unless implementation proves it is necessary.

### 7.2 Service responsibilities

| Service | Responsibility |
|---|---|
| `frontend` | React user interface |
| `backend` | API, authentication/demo user handling, accounting business logic, financial calculations |
| `demobank` | Simulated external bank API and deterministic data/scenario generation |
| `worker` | Scheduled synchronization, data processing, and bounded retry jobs |
| `db` | PostgreSQL persistence |
| Observability services | Collect, store, and display telemetry |

For a small MVP, the services may use one PostgreSQL server with clearly separated tables/schemas. DemoBank's API boundary should remain separate so that LedgerLens cannot bypass the integration by reading DemoBank tables directly.

### 7.3 High-level architecture

```text
                 +-----------------------+
                 |      React UI         |
                 | Dashboard / Invoices  |
                 | Transactions / Alerts |
                 +-----------+-----------+
                             |
                             v
                 +-----------------------+
                 |    FastAPI Backend    |
                 | Accounting Services   |
                 | Reconciliation        |
                 | Anomaly Rules         |
                 +-----------+-----------+
                             |
                             v
                 +-----------------------+       +----------------------+
                 |      PostgreSQL       |<------| Background Worker    |
                 | LedgerLens Records    |       | Scheduled Sync       |
                 +-----------------------+       | Retry / Processing   |
                                                  +----------+-----------+
                                                             |
                                                             | HTTP API
                                                             v
                                                  +----------------------+
                                                  |      DemoBank        |
                                                  | Accounts / Balances  |
                                                  | Transactions         |
                                                  | Demo Scenarios       |
                                                  +----------------------+

                 +-----------------------+
                 | Runtime AI Agents     |
                 | Financial Analyst     |
                 | On-call Responder     |
                 +-----------------------+

                 +-----------------------+
                 | OpenTelemetry         |
                 | Metrics / Traces /    |
                 | Structured Logs       |
                 +-----------------------+
```

## 8. Initial data model

The following entities are sufficient for the MVP. Exact fields and relationships should be finalized in the database design task.

| Entity | Purpose / example fields |
|---|---|
| `Company` | Single fictional business and base currency |
| `BankAccount` | Provider, external account ID, display name, currency, last successful sync |
| `BankTransaction` | Provider transaction ID, account, dates, amount, direction, counterparty, description/reference, category |
| `Counterparty` | Customer or supplier identity used in matching and reporting |
| `Invoice` | Type (payable/receivable), invoice number, counterparty, issue/due dates, total, paid, outstanding, status |
| `TransactionMatch` | Transaction, invoice, match status, match evidence, reviewer/action |
| `ExpenseCategory` | Category name and categorization rules |
| `InventorySnapshot` | Period, opening inventory, closing inventory |
| `PurchaseRecord` | Purchase date, supplier, amount, whether purchase contributes to inventory |
| `SalesRecord` | Period/date and revenue amount |
| `Anomaly` | Type, affected record, rule, evidence, severity, status |
| `Alert` | Alert type, message, status, created/resolved timestamps |
| `ImportJob` | Provider, account, cursor, start/end time, status, records fetched/created, error summary |
| `Incident` | Operational alert, investigation, actions, verification and outcome |

### Data integrity requirements

- Store amounts using fixed-precision decimal or integer minor units (for example, cents), not binary floating-point arithmetic.
- Store currency explicitly even though the MVP only supports EUR.
- Preserve provider transaction IDs and source metadata needed for idempotency and auditing.
- Do not overwrite imported bank transaction facts with AI-generated values.
- Keep invoice totals, paid amounts, and outstanding amounts internally consistent.
- Record reconciliation decisions and agent actions so changes can be audited.

## 9. Financial calculations and anomaly rules

### 9.1 AP and AR outstanding amounts

`Outstanding = Invoice Total - Amount Paid`

An invoice is overdue if its due date is before the current date and its outstanding amount is greater than zero.

Example aging buckets:

- Not overdue / current
- 1–30 days overdue
- 31–60 days overdue
- 61–90 days overdue
- More than 90 days overdue

Use one consistently documented convention for the MVP. Do not mix "0–30 days from invoice date" with "days overdue".

### 9.2 COGS and gross margin

`COGS = Opening Inventory + Inventory Purchases - Closing Inventory`

`Gross Profit = Revenue - COGS`

`Gross Margin (%) = (Gross Profit / Revenue) * 100`

Handle zero revenue explicitly to avoid division-by-zero errors. Explain in documentation that this is a simplified periodic inventory calculation, not a complete inventory valuation system.

### 9.3 Initial anomaly rules

Start with transparent, deterministic rules:

1. **Possible duplicate payment:** same or very similar amount, counterparty, direction, and reference within a defined period.
2. **Unfamiliar counterparty:** no previous transaction with the counterparty.
3. **Unusually large expense:** amount exceeds a configurable absolute threshold or a historical category/vendor baseline.
4. **Category spending increase:** current-period category spending materially exceeds its historical baseline.
5. **Unmatched transaction:** transaction remains unmatched after the reconciliation process.
6. **Overdue invoice:** positive outstanding balance after due date.
7. **COGS/margin movement:** COGS or gross margin changes materially compared with the prior period.

Thresholds should be configurable and documented. The application must present these as potential issues for review, not confirmed fraud or accounting errors.

## 10. User interface pages

1. **Overview:** cash balance, recent revenue/expense totals, AP, AR, alerts, latest synchronization status.
2. **Transactions:** bank transactions, search/filter, categories, anomaly flags.
3. **Reconciliation:** suggested matches, confirmed matches, unmatched items.
4. **Expenses:** category/vendor spending, period comparisons, unusual changes.
5. **Receivables:** customer invoices, outstanding balances, aging, overdue items.
6. **Payables:** supplier bills, outstanding balances, aging, upcoming payments.
7. **Profitability:** revenue, purchases, COGS, gross profit, gross margin.
8. **Insights & Alerts:** financial investigation results, business alerts, operational incidents.
9. **Data Sources:** DemoBank connection status, last successful sync, import history, and simulation controls in local/demo mode.

The UI should clearly identify demo/simulated financial data. Avoid implying that the app is connected to a real bank.

## 11. Testing strategy

Tests should run through a single documented command, such as `make test` or a simple equivalent.

### Unit tests

- Transaction normalization and validation.
- Idempotency/deduplication logic.
- Expense categorization rules.
- Duplicate-payment detection.
- AP/AR outstanding and aging calculations.
- Reconciliation candidate scoring.
- COGS, gross profit, and gross margin calculations.
- Alert threshold evaluation.
- Responder retry limit/backoff policy.

### Integration tests

- Start DemoBank and LedgerLens services against a test database.
- Synchronize transactions from DemoBank into LedgerLens PostgreSQL.
- Run synchronization twice and verify that no duplicates are created.
- Trigger a DemoBank API failure and verify import-job error recording and operational alert creation.
- Restore DemoBank and verify the responder's permitted retry and recovery check.
- Match a bank transaction to an invoice and verify its outstanding balance changes correctly.
- Recompute a monthly COGS/profitability report from the test records.

### Frontend tests

- Display loaded accounts and transactions.
- Filter/search transaction rows.
- Display invoice aging and outstanding balances.
- Review an anomaly and show its evidence.
- Display operational incident and recovery status.

Use deterministic seed data so tests and demonstrations are reproducible.

## 12. Observability, alerting, and on-call response

### 12.1 Key user journey to instrument

Instrument the journey:

**DemoBank request → fetch transactions → validate/normalize → persist new transactions → trigger financial analysis → update dashboard data.**

Correlate logs, metrics, and traces using trace IDs. Do not send customer names, account identifiers, IBANs, transaction descriptions, credentials, or other sensitive financial content to telemetry. Use synthetic IDs and safe summaries where needed.

### 12.2 Useful metrics

- `bank_sync_success_total`
- `bank_sync_failure_total`
- `bank_sync_duration_seconds`
- `bank_sync_last_success_timestamp`
- `bank_transactions_fetched_total`
- `bank_transactions_created_total`
- `bank_transactions_duplicate_skipped_total`
- `bank_transactions_unmatched_total`
- `invoice_reconciliation_success_total`
- `financial_alerts_created_total`
- API request latency and error rate for the user-facing application

Use metric labels carefully. Do not put transaction IDs, customer names, or other high-cardinality/sensitive values into metric labels.

### 12.3 Example operational alert

Trigger an operational alert when either:

- three consecutive synchronization attempts fail; or
- the last successful synchronization is older than the configured freshness threshold (for example, 30 minutes in the demo configuration).

The threshold should be configurable and suitable for the chosen sync schedule. A two-minute local demo poll interval and a 30-minute stale threshold are example values, not universal production defaults.

### 12.4 On-call responder workflow

1. Alert fires.
2. Responder receives the alert ID and safe diagnostic context.
3. It retrieves recent import-job history, structured logs, metrics, and traces.
4. It classifies the likely problem (timeout, temporary server error, invalid credentials/configuration, malformed data, or persistent outage).
5. It selects an allowed action from a narrow tool list.
6. For a transient error, it attempts a bounded retry with backoff or re-queues the failed job.
7. It verifies a successful synchronization and checks that new data is persisted.
8. It records the diagnosis, action, and outcome.
9. The incident is marked recovered only after verification; otherwise it stays open for human intervention.

The responder must not loop indefinitely or repeatedly call a failing dependency.

### 12.5 Telemetry UI

The course asks for metrics, traces, and structured logs to be collected, stored, correlated, and viewable. Use an OpenTelemetry-compatible setup and select a manageable dashboard/log/trace stack. A Grafana-based setup with metrics, logs, and traces is one possible route, but keep the configuration minimal enough to complete the application. Document the exact local and deployed observability views.

## 13. Containerization, deployment, and CI/CD

### Local execution

The complete app, including PostgreSQL and DemoBank, should start with one command, for example:

```bash
docker compose up --build
```

The README should state the local URLs and any one-time setup command. Seed data should be reproducible and available without manually preparing CSV files.

### CI/CD expectations

- Every pull request runs linting, unit tests, frontend tests, and integration tests where practical.
- Merges to the main branch deploy automatically to a development/staging environment.
- Production deployment is manual/approved, as required for the top CI/CD rubric level.
- Keep the previous production image/release available for rollback.
- Document and, where possible, demonstrate the rollback procedure.

### Deployment demo

The deployed app should be reachable through a public URL or have a clear recorded/live demo. Use fictional seeded data only. Protect demo controls and avoid exposing secrets.

## 14. Documentation and context management

The repository should contain an `AGENTS.md` (or an equivalent root-level agent instruction file) that describes the project and points to modular documentation.

Suggested repository documentation:

```text
ledgerlens/
├── AGENTS.md
├── README.md
├── docs/
│   ├── product-spec.md
│   ├── architecture.md
│   ├── data-model.md
│   ├── accounting-rules.md
│   ├── agent-team.md
│   ├── development-workflow.md
│   ├── testing.md
│   ├── observability.md
│   └── runbook.md
├── frontend/
├── backend/
├── demobank/
├── worker/
├── migrations/
├── tests/
├── docker-compose.yml
├── .env.example
└── Makefile
```

The public GitHub Project/task tracker should contain small tasks with:

- A clear objective.
- Scope and relevant files/components.
- Testable acceptance criteria.
- Dependencies, if any.
- Evidence of which development agent worked on it and what tests/verification were completed.

Keep agent instructions concise. Put detailed domain rules, API contracts, test strategy, and operational procedures in the modular `docs/` files.

## 15. Proposed course MVP acceptance criteria

These acceptance criteria can be turned into GitHub issues. They should be refined before implementation.

| ID | Area | Acceptance criterion |
|---|---|---|
| AC-01 | DemoBank | DemoBank exposes health, account, balance, and transaction endpoints with stable transaction IDs. |
| AC-02 | Bank sync | LedgerLens retrieves account transactions from DemoBank through HTTP without reading DemoBank's database directly. |
| AC-03 | Automation | A background worker synchronizes transactions on a configurable schedule. |
| AC-04 | Idempotency | Repeating the same sync does not create duplicate bank transactions. |
| AC-05 | Persistence | Imported transactions remain available after application restart. |
| AC-06 | Expenses | User can view and categorize transactions and filter by category/counterparty/date. |
| AC-07 | Anomalies | Predefined duplicate/unusual-expense scenarios create reviewable anomaly records with evidence. |
| AC-08 | AP | User can create supplier bills and view outstanding and overdue balances/aging. |
| AC-09 | AR | User can create customer invoices and view outstanding and overdue balances/aging. |
| AC-10 | Reconciliation | User can review a suggested bank transaction/invoice match and accept or reject it. |
| AC-11 | COGS | COGS, gross profit, and gross margin are calculated correctly from seeded/entered monthly data. |
| AC-12 | AI investigation | Financial Analyst Agent explains a selected anomaly using retrieved records and actual calculated figures. |
| AC-13 | Alerting | A sustained DemoBank synchronization failure or stale feed triggers an operational alert. |
| AC-14 | Responder | On-call Responder investigates the incident, performs a bounded permitted retry, and verifies recovery. |
| AC-15 | Observability | Key sync journey emits correlated traces, metrics, and structured logs viewable in a UI. |
| AC-16 | Privacy | Telemetry and AI prompts exclude credentials and unnecessary sensitive financial data. |
| AC-17 | Tests | Unit, frontend, and integration tests run through one documented command and pass. |
| AC-18 | Local run | Full application, DemoBank, and database start with one Docker Compose command. |
| AC-19 | CI/CD | PR checks run automatically; staging deployment is automated; production deploy is manual; rollback is documented. |
| AC-20 | Documentation | README describes the problem, functionality, setup, demo data, architecture, and limitations. |

The course rubric has 12 criteria and 24 points in total, with 10 points required to pass. The project should aim to demonstrate all criteria, but prioritize a complete end-to-end product over adding many unfinished features.

## 16. Suggested 20-hour implementation plan

This is an aggressive timebox. The safest strategy is to complete the vertical slice (DemoBank → sync → database → dashboard) before expanding into accounting analysis.

| Phase | Time | Deliverable |
|---|---:|---|
| 1. Product specification and task planning | 1.5 h | README outline, acceptance criteria, AGENTS.md, public tracker |
| 2. DemoBank and bank synchronization | 3 h | DemoBank API, worker, normalized transactions, idempotent persistence |
| 3. AP/AR and reconciliation | 2.5 h | Invoice forms, aging calculations, basic matching |
| 4. Expenses and COGS | 2 h | Expense categories, anomaly rules, monthly profitability calculations |
| 5. Frontend | 3 h | Connected dashboard and essential pages |
| 6. AI agents and alerts | 2.5 h | Financial investigation, operational alert, responder workflow |
| 7. Testing | 1.5 h | Unit, frontend, and integration coverage |
| 8. Observability | 1.5 h | Metrics, traces, structured logs, and a useful UI |
| 9. Docker, CI/CD, deployment | 2 h | One-command local environment, automated checks, deployment and rollback |
| 10. Final verification and documentation | 0.5 h | Reviewer-ready demo and documented limitations |
| **Total** | **20 h** | **Course MVP** |

If time becomes tight, prioritize in this order:

1. DemoBank HTTP integration, scheduled sync, persistence, and idempotency.
2. A connected dashboard showing real results from the local simulated bank feed.
3. One complete financial workflow (expense anomaly plus AP/AR basics).
4. One operational alert and a bounded responder action.
5. Tests, Docker, CI/CD, deployment, and observability required by the rubric.
6. Additional charts and advanced AI features only after the core workflow works.

## 17. Explicitly out of scope for the MVP

Do not attempt to build all of accounting software in 20 hours. The following are future extensions:

- Connecting to real personal/business bank accounts.
- Multiple real Open Banking providers and production AISP authorization.
- Automatic payment initiation or money transfers.
- Payroll and tax filing/VAT return generation.
- A complete double-entry general ledger.
- Full inventory management and SKU-level costing.
- Multi-currency consolidation and foreign-exchange accounting.
- Multiple companies/tenants and complex role administration.
- Fully autonomous bookkeeping or automatic confirmation of ambiguous matches.
- Multiple external accounting/ERP integrations.

## 18. Demo walkthrough for a reviewer

A concise demonstration can show the whole product in this order:

1. Start the entire application with Docker Compose.
2. Open LedgerLens and show the DemoBank connection status.
3. Trigger or wait for a scheduled synchronization.
4. Show transactions fetched from the DemoBank HTTP API and persisted in LedgerLens.
5. Run the same sync again and show that duplicate records are not created.
6. Trigger the predefined unusual-expense or duplicate-payment scenario in DemoBank.
7. Show the new transaction arriving through the normal synchronization workflow.
8. Show the deterministic rule flagging the transaction.
9. Ask the Financial Analyst Agent to investigate; show the explanation and supporting record evidence.
10. Show AP/AR aging, a transaction/invoice match, and the COGS/gross-margin calculation using demo records.
11. Trigger a DemoBank API failure.
12. Show the user-impact/staleness alert and the trace/log evidence.
13. Show the On-call Responder's bounded retry and recovery verification.
14. Show the relevant GitHub Actions run, deployed application, and rollback instructions.

## 19. Project principles and decisions

1. **Automated first:** The primary bank-data workflow is an API integration and scheduled synchronization, not manual CSV upload.
2. **DemoBank is explicit:** Clearly label it as a simulated provider. Do not claim the application is connected to a real bank.
3. **Reproducible:** Use deterministic seed data and predefined scenarios, not unpredictable LLM-generated financial records.
4. **Accounting correctness:** Use deterministic code and fixed-precision amounts for calculations.
5. **AI as an investigator:** AI explains and investigates evidence; it does not invent amounts or make unauthorized financial decisions.
6. **Safe recovery:** The responder has a small allowlist of actions, retry limits, and recovery verification.
7. **Privacy by design:** Use only fictional records, protect secrets, and minimize sensitive data in prompts and telemetry.
8. **One coherent application:** DemoBank, LedgerLens, the AI analyst, and the responder support one end-to-end workflow rather than becoming unrelated assignments.
9. **Course rubric first:** Build the smallest complete product that demonstrates the required specification, agents, full-stack app, tests, deployment, CI/CD, observability, alerting, and responder.

## 20. Immediate next steps

Before writing application code:

1. Confirm the LedgerLens product description and the single-company retail-business scope.
2. Finalize the DemoBank API contract and transaction response schema.
3. Write the initial `AGENTS.md` and modular project documents.
4. Create the public GitHub repository and project board.
5. Create issues from AC-01 through AC-20, with dependencies and acceptance criteria.
6. Implement the DemoBank-to-LedgerLens vertical slice first.

**First implementation milestone:** A reviewer can start the project with one command, see DemoBank return fictional bank transactions over HTTP, and watch LedgerLens automatically synchronize and persist those transactions without uploading a file.
