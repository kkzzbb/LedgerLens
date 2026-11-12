import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, test, vi } from "vitest";

import type {
  AccountResponse,
  SyncResponse,
  TransactionResponse,
} from "../api/types.ts";
import { Overview } from "./Overview.tsx";

function account(overrides: Partial<AccountResponse>): AccountResponse {
  return {
    id: 1,
    provider: "demo",
    external_account_id: "acc-1",
    display_name: "Main account",
    currency: "EUR",
    last_balance: "100.00",
    last_balance_at: "2026-11-12T08:00:05Z",
    last_sync_at: "2026-11-12T08:00:05Z",
    last_sync_status: "succeeded",
    last_sync_error: null,
    last_successful_sync_at: "2026-11-12T08:00:05Z",
    ...overrides,
  };
}

const NEVER_SYNCED: Partial<AccountResponse> = {
  last_balance: null,
  last_balance_at: null,
  last_sync_at: null,
  last_sync_status: null,
  last_sync_error: null,
  last_successful_sync_at: null,
};

function tx(overrides: Partial<TransactionResponse>): TransactionResponse {
  return {
    id: 1,
    account_id: 1,
    booking_date: "2026-03-02",
    value_date: null,
    amount: "12.50",
    currency: "EUR",
    direction: "debit",
    counterparty_name: null,
    counterparty_reference: null,
    description: null,
    status: "booked",
    ...overrides,
  };
}

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

interface Backend {
  accounts?: () => Response;
  monthly?: () => Response;
  transactions?: () => Response;
  sync?: () => Response | Promise<Response>;
}

// Routes each call by path; unset routes answer with empty lists.
function mockFetch(backend: Backend) {
  const fetchMock = vi.fn((input: string, init?: RequestInit) => {
    const url = new URL(input, "http://localhost");
    if (url.pathname === "/api/sync" && init?.method === "POST") {
      return Promise.resolve(backend.sync?.() ?? json({ accounts: [], anomalies: [] }));
    }
    if (url.pathname === "/api/reports/monthly") {
      return Promise.resolve(
        backend.monthly?.() ??
          json({ from: "", to: "", currency: "EUR", months: [] }),
      );
    }
    if (url.pathname === "/api/accounts") {
      return Promise.resolve(backend.accounts?.() ?? json({ accounts: [] }));
    }
    return Promise.resolve(
      backend.transactions?.() ??
        json({ items: [], total: 0, limit: 5, offset: 0 }),
    );
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function accountsBody(...accounts: AccountResponse[]) {
  return () => json({ accounts });
}

function syncCalls(fetchMock: ReturnType<typeof mockFetch>) {
  return fetchMock.mock.calls.filter(([url]) => url === "/api/sync").length;
}

function renderPage(today?: Date) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <Overview today={today} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return client;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("account cards", () => {
  test("show name, exact balance, status and UTC time", async () => {
    mockFetch({
      accounts: accountsBody(
        account({ id: 1, display_name: "Main", last_balance: "123456789.01" }),
        account({
          id: 2,
          display_name: "Card",
          last_balance: "-5000.00",
          last_sync_at: "2026-11-12T09:30:00+01:00",
        }),
      ),
    });
    renderPage();

    const main = await screen.findByRole("article", { name: "Main" });
    expect(within(main).getByText("€123,456,789.01")).toBeInTheDocument();
    expect(within(main).getByText("Synced")).toBeInTheDocument();
    expect(within(main).getByText("2026-11-12 08:00 UTC")).toBeInTheDocument();
    const card = screen.getByRole("article", { name: "Card" });
    expect(within(card).getByText("-€5,000.00")).toBeInTheDocument();
    expect(within(card).getByText("2026-11-12 08:30 UTC")).toBeInTheDocument();
  });

  test("a never-synced account waits and shows no balance", async () => {
    mockFetch({
      accounts: accountsBody(account({ display_name: "New", ...NEVER_SYNCED })),
    });
    renderPage();

    const card = await screen.findByRole("article", { name: "New" });
    expect(card).toHaveTextContent(/^NewWaiting for first sync$/);
    expect(card).not.toHaveTextContent("€");
  });

  test("each status has its text", async () => {
    mockFetch({
      accounts: accountsBody(
        account({
          id: 1,
          display_name: "A",
          last_sync_status: "succeeded_with_errors",
          last_sync_error: "2 rejected",
        }),
        account({
          id: 2,
          display_name: "B",
          last_sync_status: "failed",
          last_sync_error: "timeout",
          last_sync_at: "2026-11-12T10:00:00Z",
          last_successful_sync_at: "2026-11-11T07:05:00Z",
        }),
        account({
          id: 3,
          display_name: "C",
          last_balance: null,
          last_sync_status: "failed",
          last_sync_error: "auth",
          last_successful_sync_at: null,
        }),
        account({ id: 4, display_name: "D", last_sync_status: "paused" }),
      ),
    });
    renderPage();

    const a = await screen.findByRole("article", { name: "A" });
    expect(within(a).getByText("Synced with errors: 2 rejected")).toBeVisible();
    const b = screen.getByRole("article", { name: "B" });
    expect(within(b).getByText("Sync failed: timeout")).toBeVisible();
    expect(
      within(b).getByText("Last successful sync: 2026-11-11 07:05 UTC"),
    ).toBeVisible();
    const c = screen.getByRole("article", { name: "C" });
    expect(within(c).getByText("Sync failed: auth")).toBeVisible();
    expect(c).not.toHaveTextContent("Last successful sync");
    expect(c).not.toHaveTextContent("€");
    const d = screen.getByRole("article", { name: "D" });
    expect(within(d).getByText("paused")).toBeVisible();
  });

  test("an empty list asks for a sync", async () => {
    mockFetch({ accounts: accountsBody() });
    renderPage();

    expect(
      await screen.findByText("No accounts yet. Run a sync to load them."),
    ).toBeInTheDocument();
  });
});

describe("sync", () => {
  test("disables the button while running and sends one request", async () => {
    let finish: (response: Response) => void = () => undefined;
    const fetchMock = mockFetch({
      accounts: accountsBody(account({})),
      sync: () =>
        new Promise<Response>((resolve) => {
          finish = resolve;
        }),
    });
    renderPage();
    await screen.findByRole("article", { name: "Main account" });

    const button = screen.getByRole("button", { name: "Sync now" });
    fireEvent.click(button);
    const syncing = await screen.findByRole("button", { name: "Syncing…" });
    expect(syncing).toBeDisabled();
    fireEvent.click(syncing);
    expect(syncCalls(fetchMock)).toBe(1);

    finish(json({ accounts: [], anomalies: [] } satisfies SyncResponse));
    expect(
      await screen.findByRole("button", { name: "Sync now" }),
    ).toBeEnabled();
  });

  test("a 200 refetches accounts and transactions and shows the new status", async () => {
    let synced = false;
    const fetchMock = mockFetch({
      accounts: () =>
        synced
          ? json({
              accounts: [
                account({
                  last_sync_status: "failed",
                  last_sync_error: "timeout",
                }),
              ],
            })
          : json({ accounts: [account({ ...NEVER_SYNCED })] }),
      sync: () => {
        synced = true;
        return json({
          accounts: [
            {
              account_id: 1,
              external_account_id: "acc-1",
              status: "failed",
              created_count: 0,
              skipped_count: 0,
              rejected_count: 0,
              error: "timeout",
            },
          ],
          anomalies: [],
        } satisfies SyncResponse);
      },
    });
    renderPage();
    await screen.findByText("Waiting for first sync");
    const before = fetchMock.mock.calls.length;

    fireEvent.click(screen.getByRole("button", { name: "Sync now" }));

    expect(await screen.findByText("Sync failed: timeout")).toBeInTheDocument();
    const after = fetchMock.mock.calls.slice(before).map(([url]) => url);
    expect(after).toEqual(
      expect.arrayContaining([
        "/api/sync",
        "/api/accounts",
        "/api/transactions?limit=5",
      ]),
    );
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  test("a 502 says the sync failed and keeps the cards", async () => {
    mockFetch({
      accounts: accountsBody(account({})),
      sync: () => json({ detail: "connection" }, 502),
    });
    renderPage();
    await screen.findByRole("article", { name: "Main account" });

    fireEvent.click(screen.getByRole("button", { name: "Sync now" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /^Sync failed: connection$/,
    );
    expect(
      screen.getByRole("article", { name: "Main account" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sync now" })).toBeEnabled();
  });

  test("a network error says the sync failed and keeps the page", async () => {
    mockFetch({
      accounts: accountsBody(account({})),
      transactions: () =>
        json({
          items: [tx({ counterparty_name: "Acme GmbH" })],
          total: 1,
          limit: 5,
          offset: 0,
        }),
      sync: () => Promise.reject(new TypeError("Failed to fetch")),
    });
    renderPage();
    await screen.findByRole("article", { name: "Main account" });
    await screen.findByText("Acme GmbH");

    fireEvent.click(screen.getByRole("button", { name: "Sync now" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /^Sync failed: Network error$/,
    );
    expect(
      screen.getByRole("article", { name: "Main account" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Acme GmbH")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sync now" })).toBeEnabled();
  });
});

describe("sync anomaly count", () => {
  function syncWith(anomalies: SyncResponse["anomalies"]) {
    return () => json({ accounts: [], anomalies } satisfies SyncResponse);
  }

  test("sums new potential issues, links to alerts and invalidates them", async () => {
    mockFetch({
      sync: syncWith([
        { rule: "possible_duplicate", created_count: 2, error: null },
        { rule: "large_expense", created_count: 1, error: null },
      ]),
    });
    const client = renderPage();
    client.setQueryData(["anomalies", {}], { items: [] });

    fireEvent.click(screen.getByRole("button", { name: "Sync now" }));

    const link = await screen.findByRole("link", {
      name: "New potential issues: 3",
    });
    expect(link).toHaveAttribute("href", "/alerts");
    expect(
      screen.queryByText("Some anomaly checks did not run"),
    ).not.toBeInTheDocument();
    expect(client.getQueryState(["anomalies", {}])?.isInvalidated).toBe(true);
  });

  test("zero shows the count without a link", async () => {
    mockFetch({
      sync: syncWith([
        { rule: "possible_duplicate", created_count: 0, error: null },
        { rule: "large_expense", created_count: 0, error: null },
      ]),
    });
    renderPage();

    fireEvent.click(screen.getByRole("button", { name: "Sync now" }));

    expect(
      await screen.findByText("New potential issues: 0"),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: /New potential issues/ }),
    ).not.toBeInTheDocument();
  });

  test("a rule error says some checks did not run", async () => {
    mockFetch({
      sync: syncWith([
        { rule: "possible_duplicate", created_count: 1, error: "timeout" },
        { rule: "large_expense", created_count: 0, error: null },
      ]),
    });
    renderPage();

    fireEvent.click(screen.getByRole("button", { name: "Sync now" }));

    expect(
      await screen.findByText("Some anomaly checks did not run"),
    ).toBeInTheDocument();
    expect(screen.getByText("New potential issues: 1")).toBeInTheDocument();
  });
});

describe("recent transactions", () => {
  test("lists the 5 newest with a link to all transactions", async () => {
    const fetchMock = mockFetch({
      transactions: () =>
        json({
          items: [
            tx({
              id: 2,
              booking_date: "2026-03-05",
              amount: "1200.00",
              direction: "credit",
              counterparty_name: "Acme GmbH",
              description: "Invoice 42",
            }),
            tx({ id: 1, description: "Card fee" }),
          ],
          total: 2,
          limit: 5,
          offset: 0,
        }),
    });
    renderPage();

    const section = screen.getByRole("region", { name: "Recent transactions" });
    const table = await within(section).findByRole("table");
    const rows = within(table).getAllByRole("row").slice(1);
    expect(
      rows.map((row) =>
        within(row)
          .getAllByRole("cell")
          .map((td) => td.textContent),
      ),
    ).toEqual([
      ["2026-03-05", "Acme GmbH", "€1,200.00"],
      ["2026-03-02", "Card fee", "-€12.50"],
    ]);
    expect(fetchMock.mock.calls.map(([url]) => url)).toContain(
      "/api/transactions?limit=5",
    );
    expect(within(section).getByRole("link")).toHaveAttribute(
      "href",
      "/transactions",
    );
  });

  test("with none it shows an empty state", async () => {
    mockFetch({});
    renderPage();

    expect(await screen.findByText("No transactions yet.")).toBeInTheDocument();
  });
});

describe("separate states", () => {
  test("an accounts error leaves the transactions on screen", async () => {
    mockFetch({
      accounts: () => json({ detail: "database unavailable" }, 503),
      transactions: () =>
        json({
          items: [tx({ counterparty_name: "Acme GmbH" })],
          total: 1,
          limit: 5,
          offset: 0,
        }),
    });
    renderPage();

    const accounts = screen.getByRole("region", { name: "Accounts" });
    expect(await within(accounts).findByRole("alert")).toHaveTextContent(
      "database unavailable",
    );
    const recent = screen.getByRole("region", { name: "Recent transactions" });
    expect(await within(recent).findByText("Acme GmbH")).toBeInTheDocument();
    expect(within(recent).queryByRole("alert")).not.toBeInTheDocument();
  });
});

describe("money in / out per month", () => {
  test("lists each month with formatted amounts", async () => {
    const fetchMock = mockFetch({
      monthly: () =>
        json({
          from: "2025-08",
          to: "2026-01",
          currency: "EUR",
          months: [
            {
              month: "2025-12",
              money_in: "2500.00",
              money_out: "1234.50",
              net: "1265.50",
            },
            {
              month: "2026-01",
              money_in: "0.00",
              money_out: "300.00",
              net: "-300.00",
            },
          ],
        }),
    });
    renderPage(new Date(2026, 0, 15));

    const section = screen.getByRole("region", {
      name: "Money in / out per month",
    });
    const table = await within(section).findByRole("table");
    expect(
      within(table)
        .getAllByRole("row")
        .map((row) =>
          within(row)
            .queryAllByRole("cell")
            .map((td) => td.textContent),
        ),
    ).toEqual([
      [],
      ["2025-12", "€2,500.00", "€1,234.50", "€1,265.50"],
      ["2026-01", "€0.00", "€300.00", "-€300.00"],
    ]);
    expect(fetchMock.mock.calls.map(([url]) => url)).toContain(
      "/api/reports/monthly?from=2025-08&to=2026-01",
    );
  });

  test("all-zero months show the empty state", async () => {
    mockFetch({
      monthly: () =>
        json({
          from: "2026-01",
          to: "2026-01",
          currency: "EUR",
          months: [
            { month: "2026-01", money_in: "0.00", money_out: "0.00", net: "0.00" },
          ],
        }),
    });
    renderPage();

    expect(
      await screen.findByText("No transactions in this period."),
    ).toBeInTheDocument();
  });

  test("a successful sync refreshes the monthly and expenses reports", async () => {
    let synced = false;
    mockFetch({
      monthly: () =>
        json({
          from: "2026-01",
          to: "2026-01",
          currency: "EUR",
          months: [
            synced
              ? {
                  month: "2026-01",
                  money_in: "100.00",
                  money_out: "40.00",
                  net: "60.00",
                }
              : {
                  month: "2026-01",
                  money_in: "0.00",
                  money_out: "0.00",
                  net: "0.00",
                },
          ],
        }),
      sync: () => {
        synced = true;
        return json({ accounts: [], anomalies: [] } satisfies SyncResponse);
      },
    });
    const client = renderPage();
    const expensesKey = ["reports", "expenses", "2026-01", "2026-01"];
    client.setQueryData(expensesKey, { categories: [] });
    await screen.findByText("No transactions in this period.");

    fireEvent.click(screen.getByRole("button", { name: "Sync now" }));

    const section = screen.getByRole("region", {
      name: "Money in / out per month",
    });
    const table = await within(section).findByRole("table");
    expect(
      within(table)
        .getAllByRole("row")
        .slice(1)
        .map((row) =>
          within(row)
            .getAllByRole("cell")
            .map((td) => td.textContent),
        ),
    ).toEqual([["2026-01", "€100.00", "€40.00", "€60.00"]]);
    expect(
      screen.queryByText("No transactions in this period."),
    ).not.toBeInTheDocument();
    expect(client.getQueryState(expensesKey)?.isInvalidated).toBe(true);
  });

  test("an error stays in its section; accounts still render", async () => {
    mockFetch({
      accounts: accountsBody(account({})),
      monthly: () => json({ detail: "database unavailable" }, 503),
    });
    renderPage();

    const section = screen.getByRole("region", {
      name: "Money in / out per month",
    });
    expect(await within(section).findByRole("alert")).toHaveTextContent(
      "database unavailable",
    );
    expect(
      await screen.findByRole("article", { name: "Main account" }),
    ).toBeInTheDocument();
    const accounts = screen.getByRole("region", { name: "Accounts" });
    expect(within(accounts).queryByRole("alert")).not.toBeInTheDocument();
  });
});
