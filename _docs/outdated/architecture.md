# LedgerLens Architecture

> Status: draft v1. Source of truth for how the system is built. Product scope lives in `product-spec.md`; accounting formulas in `accounting-rules.md`; table definitions in `data-model.md`.

## 1. Architectural decisions

| # | Decision | Rationale |
|---|---|---|
| D1 | Python 3.12 + FastAPI for `backend` and `demobank` | Best fit for Decimal arithmetic, rules, and LLM tooling. OpenAPI contract for free. |
| D2 | React + TypeScript (Vite) for `frontend` | Interactive dashboard, testable with Vitest. Types generated from the backend OpenAPI schema to avoid drift between two languages. |
| D3 | PostgreSQL, SQLAlchemy 2 + Alembic | Relational financial records, constraint-based idempotency, versioned migrations. |
| D4 | **Worker is a plain async loop** (no scheduler library, no broker) | Easiest to test. Retry/backoff policy is small deterministic code that unit tests can drive with a fake clock. |
| D5 | **Grafana Cloud (free tier) for metrics, logs, traces and alert rules** | Avoids self-hosting Prometheus, Loki and Tempo inside a 1.5 h observability budget. |
| D6 | Apps emit telemetry with the OpenTelemetry SDK; a local **OTel Collector** container scrubs and forwards it | Single place to enforce privacy rules (AC-16) and to swap backends later. |
| D7 | Amounts are `NUMERIC(14,2)` in Postgres and `Decimal` in Python. Never float. | Accounting correctness. Currency stored explicitly (EUR only in MVP). |
| D8 | LLM calls use the Anthropic SDK directly with tool use; outputs validated by Pydantic | Small, auditable tool allowlists. No agent framework. |
| D9 | No message broker, no microservice framework | Out of proportion for the MVP. Postgres is the job state store. |

## 2. System context

```text
 Browser
    │ HTTPS
    ▼
 ┌──────────┐   REST/JSON   ┌───────────────────────────┐
 │ frontend │──────────────►│ backend (FastAPI)         │
 │ React/TS │               │  - REST API               │
 └──────────┘               │  - accounting services    │
                            │  - reconciliation         │
                            │  - anomaly rules          │
                            │  - agent runtime          │
                            └──────┬──────────────┬─────┘
                                   │ SQL          │ read-only tools / retry tool
                                   ▼              │
                            ┌────────────┐        │
                            │ PostgreSQL │◄───────┘
                            └─────▲──────┘
                                  │ SQL
                            ┌─────┴───────────┐  HTTP + API key   ┌──────────┐
                            │ worker          │──────────────────►│ demobank │
                            │ async sync loop │                   │ FastAPI  │
                            │ + watchdog      │                   └──────────┘
                            └─────────────────┘

 backend, worker, demobank ──OTLP──► otel-collector ──OTLP/HTTP──► Grafana Cloud
                                      (scrub PII)                  (Mimir/Loki/Tempo + Grafana UI)
```

Boundary rules:

- LedgerLens never reads DemoBank's data store. All bank data arrives over HTTP via the `BankConnector` interface.
- The frontend talks only to `backend`.
- Only `worker` calls DemoBank for synchronization. `backend` calls DemoBank only for admin scenario controls in demo mode, proxied so the browser never holds the DemoBank admin key.

## 3. Services

| Service | Tech | Responsibility | Port (local) |
|---|---|---|---|
| `frontend` | React, TypeScript, Vite, TanStack Query, Recharts | The nine UI pages. Labels all data as demo. | 5173 |
| `backend` | FastAPI, SQLAlchemy | API, accounting calculations, reconciliation, anomaly rules, alert/incident APIs, runtime agents | 8000 |
| `worker` | Python asyncio | Scheduled bank sync, post-import analysis trigger, stale/failure watchdog | none |
| `demobank` | FastAPI | Simulated bank API, deterministic seed, scenario controls | 8100 |
| `db` | PostgreSQL 16 | Persistence. Separate schemas `ledgerlens` and `demobank_sim` (DemoBank's own state is only accessed by the DemoBank service). | 5432 |
| `otel-collector` | OpenTelemetry Collector (contrib) | Receive OTLP, scrub, batch, export to Grafana Cloud | 4317/4318 |

`backend` and `worker` share one Python package (`ledgerlens/`) with separate entry points so that services, models and the connector are not duplicated. `demobank` is a separate package with no import from `ledgerlens`.

## 4. Repository layout

```text
ledgerlens/
├── AGENTS.md
├── README.md
├── docs/                  # this file and siblings
├── backend/
│   └── ledgerlens/
│       ├── api/           # FastAPI routers, request/response schemas
│       ├── domain/        # pure logic: money, aging, COGS, rules, matching
│       ├── services/      # orchestration over domain + DB
│       ├── connectors/    # BankConnector protocol + DemoBankConnector
│       ├── agents/        # analyst, responder, tool allowlists, schemas
│       ├── db/            # models, session, repositories
│       ├── telemetry/     # OTel setup, metric definitions, log scrubbing
│       └── worker/        # sync loop, retry policy, watchdog (entry point)
├── demobank/
├── frontend/
├── migrations/            # Alembic
├── observability/         # otel-collector config, Grafana dashboards/alert rules as JSON
├── tests/                 # unit/, integration/, e2e/
├── docker-compose.yml
├── .env.example
└── Makefile
```

Design rule: `domain/` has no I/O and no framework imports. Accounting math and rule logic are plain functions, which is what makes unit tests cheap and the AI-must-not-calculate rule enforceable.

## 5. Bank integration

### 5.1 Connector interface

`BankConnector` (a Python `Protocol`) exposes:

- `list_accounts() -> list[ProviderAccount]`
- `get_balance(account_id) -> ProviderBalance`
- `fetch_transactions(account_id, cursor) -> Page[ProviderTransaction]`

`DemoBankConnector` implements it over HTTP using `httpx` with explicit connect/read timeouts. A mapper converts `ProviderTransaction` to the internal `NormalizedTransaction`. Nothing outside `connectors/` knows DemoBank's field names.

### 5.2 DemoBank API contract (proposed)

| Method | Endpoint | Notes |
|---|---|---|
| GET | `/health` | Unauthenticated liveness |
| GET | `/v1/accounts` | API key required |
| GET | `/v1/accounts/{id}/balance` | |
| GET | `/v1/accounts/{id}/transactions?cursor=&limit=` | Stable ordering by `(booking_date, transaction_id)`. Returns `next_cursor`. |
| GET | `/v1/transactions/{id}` | |
| POST | `/admin/scenarios/{name}` | Demo mode only, separate admin key |
| POST | `/admin/simulation/reset` | Demo mode only |

Auth: `X-API-Key` header. Admin routes require a second key and are disabled unless `DEMOBANK_ADMIN_ENABLED=true`. Failure scenarios (`timeout`, `server_error`, `recovery`) change DemoBank's behavior for `/v1/*` so the worker experiences a realistic outage.

### 5.3 Data generation

A deterministic seed module (fixed RNG seed, stable IDs) produces about six months of history at startup if the sim schema is empty. Demo mode optionally appends one new transaction per configured interval. Scenarios inject predefined records (duplicate payment, unusual expense, category spike, cash-flow pressure). No LLM is involved.

## 6. Synchronization worker

### 6.1 Loop

One asyncio task per bank account (one in the MVP). Pseudocode of the cycle, not implementation:

```text
loop forever:
    wait until next_run (sync_interval, default 120 s in demo)
    start ImportJob(status=running, cursor=account.last_cursor)
    try:
        pages = connector.fetch_transactions(since cursor)   # bounded timeouts
        validate + normalize each record
        in ONE DB transaction:
            insert new rows ON CONFLICT (provider, external_transaction_id) DO NOTHING
            update account.last_cursor and last_successful_sync_at
            finish ImportJob(status=succeeded, counts)
        post-commit: categorize + run anomaly rules + reconciliation suggestions on new rows
    except error:
        classify error (timeout | http_5xx | auth | validation | unknown)
        finish ImportJob(status=failed, error_class, safe summary)
        schedule retry using backoff policy
```

Key properties:

- **Idempotency:** unique constraint `(provider, external_transaction_id)`. Reruns insert nothing new.
- **Cursor safety:** `last_cursor` and `last_successful_sync_at` change only in the same DB transaction as the inserts.
- **Partial validation failure:** a malformed record is rejected and recorded in the job's error summary. It does not abort the valid records in the batch. The job is marked `succeeded_with_errors` and counted by metric, and the cursor is not advanced past a record that failed because of a transient condition.
- **Testability:** the loop takes injected `clock`, `sleep`, `connector` and `session_factory`, so tests run cycles instantly with a fake clock.

### 6.2 Retry and backoff policy (worker-level)

Pure function `next_delay(attempt, config)`: exponential with cap and jitter, e.g. base 5 s, factor 2, cap 120 s, max 3 attempts per cycle. Authentication and validation errors are not retried (they cannot fix themselves). After the final attempt the cycle fails and the loop waits for the normal interval.

### 6.3 Watchdog and operational alerts

The watchdog runs in the worker on its own interval. It evaluates, deterministically, from `ImportJob` history and `last_successful_sync_at`:

- 3 consecutive failed jobs, or
- `now - last_successful_sync_at > STALE_THRESHOLD` (default 30 min in demo).

If either holds and no open sync alert exists, it creates an `Alert` (type `sync_failure` or `sync_stale`) and an `Incident` row, then requests the On-call Responder. This in-app watchdog is the source of truth for the incident workflow, so the demo works locally and offline from Grafana. A matching Grafana alert rule on the same conditions (using `bank_sync_failure_total` and `bank_sync_last_success_timestamp`) provides the metrics-side view required by the observability rubric. Grafana Cloud cannot call a webhook on `localhost`, so it is not the trigger for the responder.

## 7. Backend

### 7.1 Layers

`api` (HTTP, validation) → `services` (use cases, transactions) → `domain` (pure rules) + `db` (repositories). Routers contain no business logic.

### 7.2 Domain modules

| Module | Contents |
|---|---|
| `money` | `Decimal` helpers, rounding mode (banker's or half-up, fixed in `accounting-rules.md`), EUR enforcement |
| `aging` | outstanding amount, overdue test, bucket assignment using days-overdue convention |
| `cogs` | COGS, gross profit, gross margin with explicit zero-revenue handling |
| `categorization` | ordered deterministic rules, manual override wins |
| `anomalies` | the seven rules from the product spec, thresholds from config |
| `matching` | candidate scoring on amount, direction, date proximity, counterparty, reference, returning score and reasons |

### 7.3 Main API areas

`/api/accounts`, `/api/transactions` (filters: date, category, counterparty, anomaly status), `/api/categories`, `/api/invoices` (type payable/receivable), `/api/matches` (suggest, accept, reject, manual), `/api/reports/{overview,expenses,aging,profitability}`, `/api/inventory-snapshots`, `/api/purchases`, `/api/sales`, `/api/anomalies`, `/api/alerts`, `/api/incidents`, `/api/sync/jobs`, `/api/sync/run` (demo), `/api/demo/scenarios` (demo mode only, proxied), `/api/agents/analyst/investigate`, `/api/health`.

Authentication: single seeded demo user with a session token or static bearer for the MVP. No role administration.

### 7.4 Reconciliation behavior

Matching returns suggestions with a score and reasons, stored as `TransactionMatch(status=suggested)`. Only a user action moves a match to `accepted`. Ambiguous cases (two invoices with similar scores, or score below the confidence threshold) stay in the review queue. Accepting a match updates the invoice's `amount_paid` and `outstanding` within one DB transaction and writes an audit record.

## 8. AI agents

Both agents are implemented in `agents/` as small tool-calling loops over the Anthropic SDK. Model name comes from config.

### 8.1 Financial Analyst

- **Input:** an anomaly ID or a constrained question.
- **Tools (read-only):** `get_transaction`, `get_anomaly`, `list_counterparty_transactions`, `get_category_summary`, `get_invoice`, `get_profitability_report`. Each tool calls an existing service and returns minimal, already-computed fields.
- **Output schema (Pydantic):** `summary`, `evidence[]` (record type, record ID, figure, source tool), `confidence` (low/medium/high), `uncertainties[]`, `needs_human_review`.
- **Validation:** every figure in `evidence` must match a value returned by a tool call in the same run. Responses failing the schema or this check are discarded and surfaced as "investigation unavailable" rather than shown.
- **No write tools.**

### 8.2 On-call Responder

- **Input:** incident ID and safe diagnostic context (error classes, counts, timestamps; no payloads).
- **Read tools:** `get_import_jobs`, `get_sync_metrics_summary`, `get_recent_logs` (from a local, already-scrubbed ring buffer or Grafana Cloud's query API), `get_trace_summary`, `check_demobank_health`.
- **Action tools (allowlist):** `retry_sync_job` and `requeue_failed_job`. Both go through a policy guard.
- **Policy guard (deterministic code, not the model):** max 3 agent-initiated retries per incident, exponential backoff between them, no retry for `auth`/`validation` classes, one action in flight at a time, all calls logged to the incident. The model cannot override these limits.
- **Verification:** after an action the responder waits for the next job result via the `ImportJob` table. The incident becomes `recovered` only if a job succeeded after the action and `last_successful_sync_at` advanced. Otherwise it stays `open` with status `needs_human`.
- **Output schema:** `classification`, `diagnosis`, `actions_taken[]`, `verification_result`, `final_status`.

### 8.3 Safety constraints

- No tool can move money, edit invoice amounts, confirm a match, or modify imported bank facts.
- Prompts contain IDs, amounts, categories and counterparty display names only when needed for the analyst. No credentials, account references or free-text bank descriptions beyond what an investigation needs.
- Agent runs are stored (inputs summary, tool calls, outputs, validation result) for audit.

## 9. Data layer

Entities follow the product spec: `Company`, `BankAccount`, `BankTransaction`, `Counterparty`, `Invoice`, `TransactionMatch`, `ExpenseCategory`, `InventorySnapshot`, `PurchaseRecord`, `SalesRecord`, `Anomaly`, `Alert`, `ImportJob`, `Incident`, plus `AgentRun` and `AuditEvent`. Full definitions go in `data-model.md`.

Constraints worth fixing now:

- `BankTransaction`: unique `(provider, external_transaction_id)`; `amount NUMERIC(14,2)`; `currency CHAR(3)` with a CHECK for EUR in the MVP; raw provider payload kept in a `source_metadata JSONB` column for audit but excluded from telemetry and prompts.
- `Invoice`: CHECK `amount_paid >= 0`, `amount_paid <= total`, `outstanding = total - amount_paid` (generated column or enforced in service plus test).
- `ImportJob`: `status` enum, `error_class`, counts, and the cursor used.
- Imported transaction fields are never updated by categorization, matching or AI. Category, match and anomaly status live in separate columns or tables.

## 10. Frontend

- React + TypeScript, Vite, React Router, TanStack Query for server state.
- API types generated from the backend's OpenAPI schema (`openapi-typescript`) in a `make` step and checked in CI for drift.
- Pages: Overview, Transactions, Reconciliation, Expenses, Receivables, Payables, Profitability, Insights & Alerts, Data Sources.
- A persistent banner reads "Demo data from a simulated bank (DemoBank)". The simulation controls appear on Data Sources only when the backend reports demo mode.
- No financial calculation in the browser. The UI formats values the backend returns.
- Tests: Vitest + Testing Library with a mocked API layer.

## 11. Observability

### 11.1 Pipeline

```text
backend / worker / demobank
   OTel SDK (traces, metrics, logs)
        │ OTLP (gRPC/HTTP) over the compose network
        ▼
 otel-collector
   processors: memory_limiter → attributes/redaction → batch
        │ OTLP/HTTP + basic auth (Grafana Cloud token from .env)
        ▼
 Grafana Cloud: metrics, logs, traces, dashboards, alert rules
```

If the Grafana Cloud variables are not set, the Collector falls back to a `debug` exporter that logs to stdout, so `docker compose up` still works for reviewers without an account.

### 11.2 Instrumented journey

`DemoBank request → fetch → validate/normalize → persist → analysis trigger → dashboard data`

One root span `bank.sync.cycle` per cycle with child spans `demobank.fetch_page`, `sync.normalize`, `db.persist_batch`, `analysis.run`. `httpx`, FastAPI and SQLAlchemy auto-instrumentation propagate W3C trace context from worker to DemoBank, so one trace crosses both services. Structured JSON logs include `trace_id` and `span_id` so Grafana can link logs to traces.

### 11.3 Metrics

As listed in the product spec (`bank_sync_success_total`, `bank_sync_failure_total`, `bank_sync_duration_seconds`, `bank_sync_last_success_timestamp`, `bank_transactions_fetched_total`, `bank_transactions_created_total`, `bank_transactions_duplicate_skipped_total`, `bank_transactions_unmatched_total`, `invoice_reconciliation_success_total`, `financial_alerts_created_total`) plus HTTP request latency and error rate from FastAPI instrumentation. Allowed labels: `provider`, `outcome`, `error_class`, `alert_type`. No IDs, names or amounts as labels.

### 11.4 Grafana views and alerts (to document in `observability.md`)

- Dashboard "Bank sync health": success/failure rate, sync duration, time since last success, records fetched/created/skipped.
- Dashboard "API health": latency and error rate.
- Explore links: logs filtered by `trace_id`, and the trace waterfall for a failed cycle.
- Alert rules: "sync failures ≥ 3 consecutive" and "no successful sync for > threshold" on the metrics above.

### 11.5 Privacy controls

- Log formatter and Collector `attributes` processor drop or hash a denylist of keys (`counterparty_name`, `description`, `reference`, `iban`, `api_key`, `authorization`, and similar). The deny rule is applied in the app first and again in the Collector as defense in depth.
- SQL statements are not recorded with parameter values; DB instrumentation records the operation only.
- Span attributes use synthetic IDs and counts, never raw bank content.
- A test feeds records containing marker strings through the sync path and asserts they do not appear in captured telemetry output.
- Tokens for Grafana Cloud live only in `.env` and CI/hosting secrets. `.env.example` contains placeholders.

## 12. Configuration

All settings come from environment variables, validated at startup by a Pydantic settings class. Representative variables:

| Variable | Purpose | Demo default |
|---|---|---|
| `DATABASE_URL` | Postgres connection | compose db |
| `DEMOBANK_BASE_URL`, `DEMOBANK_API_KEY` | Connector config | compose service |
| `DEMOBANK_ADMIN_ENABLED`, `DEMOBANK_ADMIN_KEY` | Scenario controls | `true` locally, `false` when deployed publicly |
| `SYNC_INTERVAL_SECONDS` | Loop cadence | 120 |
| `SYNC_MAX_ATTEMPTS`, `SYNC_BACKOFF_BASE_SECONDS`, `SYNC_BACKOFF_CAP_SECONDS` | Backoff policy | 3, 5, 120 |
| `STALE_THRESHOLD_MINUTES`, `FAILURE_STREAK_THRESHOLD` | Watchdog | 30, 3 |
| `ANOMALY_*` | Rule thresholds | documented in `accounting-rules.md` |
| `ANTHROPIC_API_KEY`, `AGENT_MODEL` | Agents | none (agents disabled if unset) |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | App → Collector | `http://otel-collector:4318` |
| `GRAFANA_CLOUD_OTLP_ENDPOINT`, `GRAFANA_CLOUD_INSTANCE_ID`, `GRAFANA_CLOUD_TOKEN` | Collector → Grafana | empty means stdout exporter |

If `ANTHROPIC_API_KEY` is missing, the app runs and the agent endpoints return a clear "AI investigation not configured" response, so tests and local runs do not depend on a key.

## 13. Local environment

`docker compose up --build` starts `db`, `demobank`, `backend` (runs migrations on start), `worker`, `frontend`, and `otel-collector`. Startup order uses health checks (`db` healthy → `demobank` healthy → `backend`, `worker`). Seed data for LedgerLens (invoices, inventory, sales, purchases) loads via an idempotent seed command that the backend runs on first start in demo mode. `Makefile` targets: `up`, `down`, `test`, `lint`, `seed`, `reset`.

## 14. Testing architecture

| Level | Tooling | Scope |
|---|---|---|
| Unit | pytest | `domain/` functions, normalization, retry policy with fake clock, responder policy guard, rule thresholds |
| Integration | pytest + Postgres service + a real DemoBank instance (compose or CI service) | Full sync, double-sync idempotency, forced failure → job error + alert, recovery → responder retry verified, match → invoice outstanding change, COGS recompute, telemetry redaction |
| Agents | pytest with a stubbed LLM client | Schema validation, evidence-matches-tool-results check, policy guard blocks over-limit retries |
| Frontend | Vitest + Testing Library | Accounts/transactions render, filtering, aging display, anomaly evidence, incident status |
| E2E (optional) | Playwright | The demo walkthrough, if time permits |

`make test` runs lint, type checks, unit, frontend and integration tests. LLM calls are never made in the default test run.

## 15. CI/CD and deployment

- **PR workflow (GitHub Actions):** ruff, mypy/pyright, ESLint, `tsc`, pytest (unit), Vitest, integration tests with a Postgres service container, OpenAPI-types drift check, Docker image build.
- **`main` workflow:** builds and pushes versioned images (tagged with commit SHA) to GHCR, then deploys automatically to the staging environment.
- **Production:** deployed by a manually triggered workflow protected by a GitHub Environment with required reviewers, promoting an already-built image tag.
- **Rollback:** redeploy the previous image tag. The tag history is kept in GHCR. Procedure goes in `runbook.md`. Alembic migrations must be backward compatible for one release (expand/contract), so rolling back the app does not require a down-migration.
- **Hosting target:** to be decided (see open questions). Whichever is chosen must support managed Postgres, secrets, image-based deploy, and a public URL.
- **Public deployment hardening:** `DEMOBANK_ADMIN_ENABLED=false` unless explicitly demoing, rate limiting on the agent endpoints to cap LLM spend, fictional data only, secrets only in the host's secret store.

## 16. Security notes

- Secrets are never committed. `.env.example` has placeholders only.
- DemoBank admin routes are off unless enabled, and require a separate key.
- The backend validates all input with Pydantic and uses parameterized queries via SQLAlchemy.
- CORS is limited to the frontend origin.
- The agent tool layer is the only path from the LLM to data, and it exposes no write operations other than the guarded retry actions.

## 17. Known limitations

- Single company, single account, EUR only.
- Demo polling cadence does not reflect real Open Banking rate limits or consent flows.
- COGS uses a simplified periodic-inventory formula.
- Grafana Cloud free tier has retention and ingest limits, which is adequate for a demo.
- Alert-to-responder triggering is done by an in-app watchdog, not by Grafana webhooks.

## 18. Open questions

1. Hosting platform for staging/production (Fly.io, Render, Cloud Run, or a VPS with Compose).
2. Rounding convention for Decimal arithmetic (fixed in `accounting-rules.md`).
3. Whether the responder reads logs from Grafana Cloud's query API or from a local scrubbed buffer. The local buffer is simpler and works offline. The Grafana API better demonstrates the telemetry loop.
4. Whether to include Playwright E2E in the 20 h budget.
5. Which Claude model to configure for `AGENT_MODEL`.
