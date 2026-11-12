# DemoBank

DemoBank is a simulated bank: a small HTTP API that serves fictional data so
LedgerLens can be demonstrated without a real bank. No real account, person
or transaction is behind it: every name, reference and amount is made up, and
none is the name of a real company or product.

It is a separate Python 3.12 project managed with
[uv](https://docs.astral.sh/uv/), and it imports nothing from the LedgerLens
backend (`ledgerlens`).

## Install and check

```sh
cd demobank
uv sync                      # create .venv and install dev tools
uv run ruff check .          # lint
uv run ruff format --check . # formatting
uv run mypy                  # type check (strict)
uv run pytest                # tests (no database, no Docker)
```

The root `make install` and `make test` run the same steps.

### Database tests

The tests marked `db` need PostgreSQL. They are skipped unless
`TEST_DATABASE_URL` names a server where the user may create databases. Each
run creates and drops its own `demobank_test_<random hex>` database, so
nothing is written to the database the URL names. The password is masked in
test reports.

```sh
docker compose up -d db      # from the repo root
cd demobank
TEST_DATABASE_URL=postgresql://ledgerlens:ledgerlens@localhost:5432/postgres uv run pytest
uv run pytest -m db          # only the database tests
```

## Settings

Read from the process environment only (no `.env` file). An empty or blank
value counts as unset.

| Variable | Default | Meaning |
| --- | --- | --- |
| `DEMOBANK_API_KEY` | required | The key every `/v1/*` request must send in `X-API-Key` |
| `DEMOBANK_DATABASE_URL` | required | The PostgreSQL database (a secret: it holds the password). `postgresql://`, `postgres://` and `postgresql+psycopg://` are accepted; the psycopg 3 driver is used. DemoBank uses only the `demobank_sim` schema |
| `DEMOBANK_SEED` | `42` | Seed of the generated history: a non-negative integer |
| `DEMOBANK_ANCHOR_DATE` | empty | Last day of the generated history, `YYYY-MM-DD`. Empty means the date of first generation (today in UTC). A date after today is rejected |

`uv run python -m demobank.config` prints `Configuration OK`, or one line
per problem on stderr with exit status 1. No line contains a value. It checks
values only and does not connect to the database.

`DEMOBANK_SEED` and `DEMOBANK_ANCHOR_DATE` are used only when the history is
generated. Once it is stored, the stored seed and anchor date win: a restart
never shifts the data, and a different value only logs a warning.

## Run without Docker

DemoBank needs PostgreSQL. Start the Compose database, then DemoBank:

```sh
docker compose up -d db      # from the repo root
cd demobank
DEMOBANK_API_KEY=demo-api-key \
DEMOBANK_DATABASE_URL=postgresql://ledgerlens:ledgerlens@localhost:5432/ledgerlens \
  uv run uvicorn --factory demobank.app:create_app --port 8100
```

The server checks its settings when it starts and exits with an error when
one is missing or invalid. It then prepares its database (below), and exits
with `DemoBank cannot connect to the database (DEMOBANK_DATABASE_URL)` when
the database cannot be reached within 5 seconds. Then:

```sh
curl -i localhost:8100/health                                 # 200 {"status":"ok"}
curl -i localhost:8100/v1/ping                                # 401 {"error":"unauthorized"}
curl -i -H "X-API-Key: demo-api-key" localhost:8100/v1/ping   # 200 {"status":"ok"}
```

- `GET /health` is public and only says the process is up. It touches no
  database
- Every `/v1/*` route needs the `X-API-Key` header. A missing, empty or
  wrong key gets 401 `{"error":"unauthorized"}`, the same body in every case
- `/docs` and `/openapi.json` are public

### Accounts and balance

```sh
curl -H "X-API-Key: demo-api-key" localhost:8100/v1/accounts
# 200 [{"account_id":"acc_operating_001","display_name":"Demo Retail Ltd — Operating","currency":"EUR"}]

curl -H "X-API-Key: demo-api-key" localhost:8100/v1/accounts/acc_operating_001/balance
# 200 {"account_id":"acc_operating_001","balance":"15234.10","currency":"EUR","as_of":"2026-11-12T09:30:00Z"}

curl -H "X-API-Key: demo-api-key" localhost:8100/v1/accounts/acc_unknown/balance
# 404 {"error":"account_not_found"}
```

- `GET /v1/accounts` lists every account, ordered by `account_id`
- `balance` is `opening_balance` + credits − debits over every row in
  `demobank_sim.transactions` for the account, computed at request time
  (never cached). It is a string with exactly 2 decimals, never a JSON
  number
- `as_of` is the UTC time the balance was read, ISO 8601
- An unknown account ID gets 404 `{"error":"account_not_found"}`. Without a
  valid key, both routes get 401 first, also for an unknown account ID

### Transactions

```sh
curl -H "X-API-Key: demo-api-key" "localhost:8100/v1/accounts/acc_operating_001/transactions?limit=2"
# 200 {"transactions":[{"transaction_id":"txn_000001","account_id":"acc_operating_001",
#   "booking_date":"2025-12-30","value_date":"2025-12-30","amount":"1645.92","currency":"EUR",
#   "direction":"credit","counterparty_name":"Fernhollow Cafe",
#   "counterparty_reference":"DEMO-CP-0006","description":"Customer payment INV-1001",
#   "status":"booked"},{"transaction_id":"txn_000002",...}],
#   "next_cursor":"eyJiIjoiMjAyNS0xMi0zMSIsInQiOiJ0eG5fMDAwMDAyIn0=","has_more":true}
```

- `GET /v1/accounts/{account_id}/transactions?cursor=&limit=` pages through
  the account's rows in `(booking_date, transaction_id)` order, from the
  oldest when no cursor is sent
- `limit` is 1 to 500, 100 by default; outside that range gets 422
- `next_cursor` points just after the last returned record. Save it and send
  it later to get only newer records. On an empty page it is the cursor sent
  (or `null` when none was sent). `has_more` is true only when more records
  exist after the page at the time of the request
- The cursor is opaque to clients: URL-safe base64 of
  `{"b": "<booking_date>", "t": "<transaction_id>"}`, not signed. A cursor
  that does not decode gets 400 `{"error":"invalid_cursor"}`
- `amount` is always positive, a string with exactly 2 decimals; `direction`
  is `debit` or `credit`. An unknown account gets 404
  `{"error":"account_not_found"}`; without a valid key, 401

With Docker, `docker compose up --build` from the repo root starts DemoBank
on port 8100 next to the backend (see the root `README.md`).

## Generated history

On first start, DemoBank generates about six months of fictional history for
one business account and stores it in the `demobank_sim` schema. The same
seed and anchor date always give the same data. The generator is
`demobank/generator.py`: pure, with no I/O, no clock and no settings.

### Storage and startup

DemoBank shares the Compose PostgreSQL server and the `ledgerlens` database
with the backend, but reads and writes only the `demobank_sim` schema, which
it creates when it is missing:

- `simulation`: one row with the seed, the anchor date, the schema version
  and the generation time
- `accounts`: the account, with `opening_balance NUMERIC(14,2)`
- `transactions`: the transactions, with `amount NUMERIC(14,2)` (always
  positive; `direction` carries the sign) and an index on
  `(account_id, booking_date, transaction_id)`

The tables come from SQLAlchemy `create_all`, without Alembic. On startup,
when `simulation` has no row, DemoBank picks the anchor date, generates the
dataset and inserts it in one database transaction under a PostgreSQL
advisory lock, so two DemoBank processes starting together end with one
dataset. It logs one INFO line with the seed, the anchor date and the number
of transactions. When the row exists, it changes nothing.

A stored schema version that differs from the code's fails startup with one
line telling you to drop the schema.

### Regenerate with another seed or anchor date

Drop the schema and restart DemoBank:

```sh
docker compose exec db psql -U ledgerlens -d ledgerlens -c "DROP SCHEMA demobank_sim CASCADE"
docker compose restart demobank
```

Transaction IDs restart at `txn_000001`, so LedgerLens' imported data must be
reset with it: `docker compose down -v` resets both (it removes the database
volume).

### The account

| Field | Value |
| --- | --- |
| `account_id` | `acc_operating_001` |
| Display name | `Demo Retail Ltd — Operating` |
| Currency | `EUR` |
| Opening balance | `25000.00`, the balance at the start of the first day |

### History and patterns

The history covers the 183 days from `anchor_date - 182` to `anchor_date`,
both inclusive. Booking dates never depend on the seed: the seed only picks
each amount in its range (`random.Random(seed).randint` on integer cents) and
the customer of each ordinary receipt. Every amount is a `Decimal` with
exactly 2 decimal places, built from cents. Each pattern maps to one #25
category key. All amounts are in EUR:

| Pattern | #25 key | Direction | Counterparties | When | Amount per payment |
|---|---|---|---|---|---|
| Customer receipts | `revenue` | credit | a fixed list of fictional customers, picked with the seed | exactly 1 on each Monday to Friday in the history range, none on Saturday or Sunday | 1,500.00 to 2,500.00 |
| Rent | `rent` | debit | 1 landlord | day 1 of each month | 2,800.00 fixed |
| Software subscriptions | `software` | debit | 3 vendors | days 5, 12 and 20 (one vendor each) | 89.00, 129.00 and 189.00, fixed |
| Utilities | `utilities` | debit | 2 providers | days 8 and 22 | 300.00 to 340.00 (day 8), 120.00 to 140.00 (day 22) |
| Other supplier payments | `supplier_other` | debit | 2 (cleaning, bookkeeping) | days 15 and 25 | 240.00 and 380.00, fixed |
| Inventory purchases | `inventory` | debit | 3 suppliers | supplier A on days 3, 13 and 23; B on 6, 16 and 26; C on 9, 19 and 28 | 1,700.00 to 2,400.00 |

Every monthly day is between 1 and 28. A date outside the history range is
skipped, not moved. Within a day, the transactions are in this order: the
ordinary receipt, the anchored receipts, then the debits in the order of the
counterparty table below.

### Counterparties

| Counterparty | Reference | #25 key | Pattern | Day of month | Amount |
|---|---|---|---|---|---|
| Quillmere Interiors | `DEMO-CP-0001` | `revenue` | customer receipts | Monday to Friday | 1,500.00 to 2,500.00 |
| Brackenfold Events | `DEMO-CP-0002` | `revenue` | customer receipts | Monday to Friday | 1,500.00 to 2,500.00 |
| Corvanta Design Studio | `DEMO-CP-0003` | `revenue` | customer receipts | Monday to Friday | 1,500.00 to 2,500.00 |
| Duskwillow Florists | `DEMO-CP-0004` | `revenue` | customer receipts | Monday to Friday | 1,500.00 to 2,500.00 |
| Embervale Guesthouses | `DEMO-CP-0005` | `revenue` | customer receipts | Monday to Friday | 1,500.00 to 2,500.00 |
| Fernhollow Cafe | `DEMO-CP-0006` | `revenue` | customer receipts | Monday to Friday | 1,500.00 to 2,500.00 |
| Halvenmoor Properties | `DEMO-CP-0011` | `rent` | rent | 1 | 2,800.00 |
| Ledgerkite Cloud | `DEMO-CP-0021` | `software` | software subscription | 5 | 89.00 |
| Pixelquarry Design Suite | `DEMO-CP-0022` | `software` | software subscription | 12 | 129.00 |
| Tallowfield Till Systems | `DEMO-CP-0023` | `software` | software subscription | 20 | 189.00 |
| Wattmere Energy | `DEMO-CP-0031` | `utilities` | utilities | 8 | 300.00 to 340.00 |
| Rillbourne Water | `DEMO-CP-0032` | `utilities` | utilities | 22 | 120.00 to 140.00 |
| Sparkvale Cleaning | `DEMO-CP-0041` | `supplier_other` | other supplier payments | 15 | 240.00 |
| Tallyhook Bookkeeping | `DEMO-CP-0042` | `supplier_other` | other supplier payments | 25 | 380.00 |
| Orchardine Wholesale (A) | `DEMO-CP-0051` | `inventory` | inventory purchases | 3, 13, 23 | 1,700.00 to 2,400.00 |
| Brimcastle Trading (B) | `DEMO-CP-0052` | `inventory` | inventory purchases | 6, 16, 26 | 1,700.00 to 2,400.00 |
| Quaymoss Supplies (C) | `DEMO-CP-0053` | `inventory` | inventory purchases | 9, 19, 28 | 1,700.00 to 2,400.00 |

#14 reuses these ranges, and #25's DemoBank fixture uses this counterparty
list. Changing any value means rerunning the range checks in
`tests/unit/test_generator_invariants.py`.

### References

Each transaction has these fields: `transaction_id`, `account_id`,
`booking_date`, `value_date` (equal to `booking_date`), `amount`, `currency`
(`EUR`), `direction` (`debit` or `credit`), `counterparty_name`,
`counterparty_reference`, `description` and `status` (`booked`).

- Transaction IDs: `txn_` and a 6-digit sequence (`txn_000001`, ...) in
  `(booking_date, schedule order)` order, then the planted anomalies, so
  sorting by `transaction_id` and by `(booking_date, transaction_id)` give
  the same order
- Invoice numbers: each ordinary customer receipt's `description` holds one,
  `Customer payment INV-1001` and up in booking order. The scheme does not
  depend on the calendar year. With about 131 weekdays in 183 days, the
  sequence ends near `INV-1131`. `INV-9001` and up are reserved for the
  anchored receipts
- Bill numbers: each inventory purchase's `description` holds one,
  `Inventory purchase BILL-1001` and up in booking order (at most 63 in 183
  days)
- Counterparty references: `DEMO-CP-` and a 4-digit number per counterparty
  (the table above), in `counterparty_reference`
- The other debits are described as `Shop rent`, `Software subscription`,
  `Utility bill` or `Service fee`, followed by the month (`2026-06`)

### Anchored receipts (for #44)

These customer receipts are the same for every seed. Each is booked a fixed
number of days before `anchor_date`, on top of the ordinary receipt of that
day. LedgerLens' demo seed (#44) relies on them: **#44's seed must change
with this list** (`ANCHORED_RECEIPTS` in `demobank/generator.py`).

| Booked on | Customer | Amount | Description |
|---|---|---|---|
| `anchor_date - 1` | Quillmere Interiors | 1,845.00 | `Customer payment INV-9001` |
| `anchor_date - 4` | Corvanta Design Studio | 2,120.00 | `Customer payment INV-9002` |
| `anchor_date - 9` | Embervale Guesthouses | 1,675.50 | `Customer payment INV-9003` |
| `anchor_date - 13` | Brackenfold Events | 2,340.00 | `Customer payment INV-9004` |
| `anchor_date - 18` | Duskwillow Florists | 1,990.00 | `Customer payment INV-9005` |
| `anchor_date - 26` | Fernhollow Cafe | 2,210.00 | `Customer payment` (no invoice number: an unmatched incoming payment) |

### Planted anomalies (#12)

Every dataset ends with these 3 debits, the same for every seed, all booked
(and valued) on `anchor_date` after the history, with the next transaction
IDs (`txn_<N+1>` to `txn_<N+3>` after the last history row `txn_<N>`). They
sort after every history row, so a sync's cursor (#11) never skips them:

| Scenario | Counterparty | Reference | Amount | Description |
|---|---|---|---|---|
| `duplicate_payment` (1st) | Sparkvale Cleaning | `DEMO-CP-0041` | 455.00 | `Deep clean SVC-9001` |
| `duplicate_payment` (2nd) | Sparkvale Cleaning | `DEMO-CP-0041` | 455.00 | `Deep clean SVC-9001` |
| `unusual_expense` | Orchardine Wholesale | `DEMO-CP-0051` | 7850.00 | `Inventory purchase BILL-9001` |

They give LedgerLens' anomaly rules one possible duplicate payment (#28: the
2nd row, 0 days and 0.00 apart from the 1st) and one unusually large expense
(#30: above 5,000.00 and above 3 times Orchardine's baseline). They are
potential issues for review, never fraud. `SVC-9001` and `BILL-9001` are
outside the ordinary sequences.

LedgerLens evaluates only the rows booked in the last 7 days (#32), and
`anchor_date` defaults to the day of first generation, so the first sync
after a fresh start flags them. With an older `DEMOBANK_ANCHOR_DATE`, or a
dataset more than 6 days old, they fall outside the window and are history
only.

To replay them, reset everything and start again: `docker compose down -v`,
then `docker compose up --build`. This also resets LedgerLens' data (see
"Regenerate with another seed or anchor date"). There is no route or setting
to trigger them on demand.

### Guarantees

For every seed and every anchor date, by construction (the dates are fixed
and the amount ranges are narrow):

- the running balance never goes below 0, in `(booking_date,
  transaction_id)` order, with the planted anomalies. The lowest balance
  possible, with every debit at its maximum and every credit at its minimum,
  is 18,900.00 (the planted anomalies, on the last day, do not lower it)
- total credits exceed total debits
- the history without the planted anomalies trips none of LedgerLens' transaction rules #28 to
  #31 at their default thresholds, over the 7-day evaluation window ending on
  `anchor_date` (#32): no debit above 5,000.00 or above 3 times its vendor or
  category baseline, no possible duplicate (same-counterparty debits are at
  least 4 days apart), no unfamiliar counterparty in the window, and no
  category increase

The unmatched-transaction rule (#39) is not covered: it will flag the
ordinary customer receipts booked 8 to 60 days before LedgerLens' `as_of`
that have no accepted match (about 37), and the anchored receipt without an
invoice number. This is expected.

With the planted anomalies, the full dataset has exactly one possible
duplicate (#28) and one large expense (#30) in the window.

The tests check these through range checks on the constants, the worst case
of the schedule for every anchor date from 2024 to 2029, and a property test
over 200 seeds.

### Golden hash

`generate(42, date(2026, 6, 30))` has the SHA-256
`d525a15f65d98dd19fcff99cad033158f31c611a73329d9aac371e631027eb3d` over the
canonical serialisation in `tests/unit/test_generator.py`. The test fails on
any change to the data. Update the constant on purpose only, and update this
hash and #44's data with it.
