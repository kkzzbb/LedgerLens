import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, test, vi } from "vitest";

import type {
  AnomalyFlagListResponse,
  AnomalyFlagResponse,
  FlaggedTransactionResponse,
} from "../api/types.ts";
import { Alerts } from "./Alerts.tsx";

function flaggedTx(
  overrides: Partial<FlaggedTransactionResponse>,
): FlaggedTransactionResponse {
  return {
    id: 1,
    booking_date: "2026-03-02",
    counterparty_name: null,
    amount: "12.50",
    category: null,
    ...overrides,
  };
}

function flag(overrides: Partial<AnomalyFlagResponse>): AnomalyFlagResponse {
  return {
    id: 1,
    rule: "large_expense",
    status: "open",
    reason: "Much larger than usual",
    created_at: "2026-03-03T08:00:00Z",
    reviewed_at: null,
    transaction: flaggedTx({}),
    related_transaction: null,
    ...overrides,
  };
}

function page(
  items: AnomalyFlagResponse[],
  total = items.length,
  offset = 0,
): AnomalyFlagListResponse {
  return { items, total, limit: 50, offset };
}

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

interface Backend {
  list: (url: URL) => Response;
  review?: (id: string) => Response | Promise<Response>;
}

function mockFetch(backend: Backend) {
  const fetchMock = vi.fn((input: string, init?: RequestInit) => {
    const url = new URL(input, "http://localhost");
    const match = /^\/api\/anomalies\/(\d+)\/review$/.exec(url.pathname);
    if (match && init?.method === "POST") {
      return Promise.resolve(
        backend.review?.(match[1]) ?? json(flag({ status: "reviewed" })),
      );
    }
    return Promise.resolve(backend.list(url));
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function listCalls(fetchMock: ReturnType<typeof mockFetch>) {
  return fetchMock.mock.calls
    .map(([url]) => url)
    .filter((url) => url.startsWith("/api/anomalies?"));
}

function lastParams(fetchMock: ReturnType<typeof mockFetch>) {
  const calls = listCalls(fetchMock);
  const url = calls[calls.length - 1];
  return Object.fromEntries(new URL(url, "http://localhost").searchParams);
}

function reviewCalls(fetchMock: ReturnType<typeof mockFetch>) {
  return fetchMock.mock.calls.filter(([url]) => url.endsWith("/review"));
}

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <Alerts />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function cells() {
  return screen
    .getAllByRole("row")
    .slice(1)
    .map((row) =>
      within(row)
        .getAllByRole("cell")
        .map((td) => td.textContent),
    );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

const DUPLICATE = flag({
  id: 2,
  rule: "possible_duplicate",
  reason: "Same amount and counterparty within 3 days",
  transaction: flaggedTx({
    id: 20,
    booking_date: "2026-03-05",
    counterparty_name: "Acme GmbH",
    amount: "1250.00",
    category: "software",
  }),
  related_transaction: flaggedTx({
    id: 19,
    booking_date: "2026-03-03",
    counterparty_name: "Acme GmbH",
    amount: "1250.00",
  }),
});

const LARGE = flag({ id: 1 });

describe("table", () => {
  test("shows labels and transaction fields for both rules", async () => {
    mockFetch({ list: () => json(page([DUPLICATE, LARGE])) });
    renderPage();

    expect(screen.getByRole("heading", { name: "Alerts" })).toBeInTheDocument();
    await screen.findByRole("table");
    expect(
      screen.getAllByRole("columnheader").map((th) => th.textContent),
    ).toEqual([
      "Rule",
      "Date",
      "Counterparty",
      "Amount",
      "Category",
      "Reason",
      "Related transaction",
      "Status",
    ]);
    expect(cells()).toEqual([
      [
        "Possible duplicate payment",
        "2026-03-05",
        "Acme GmbH",
        "€1,250.00",
        "software",
        "Same amount and counterparty within 3 days",
        "2026-03-03 · Acme GmbH · €1,250.00",
        "Mark reviewed",
      ],
      [
        "Unusually large expense",
        "2026-03-02",
        "—",
        "€12.50",
        "Uncategorized",
        "Much larger than usual",
        "—",
        "Mark reviewed",
      ],
    ]);
  });

  test('a reviewed flag shows "Reviewed" and no button', async () => {
    mockFetch({ list: () => json(page([flag({ status: "reviewed" })])) });
    renderPage();

    await screen.findByRole("table");
    expect(cells()[0][7]).toBe("Reviewed");
    expect(
      screen.queryByRole("button", { name: "Mark reviewed" }),
    ).not.toBeInTheDocument();
  });

  test("the table, labels and empty states never say fraud or error", async () => {
    let total = 2;
    mockFetch({
      list: () => json(total ? page([DUPLICATE, LARGE]) : page([])),
    });
    renderPage();

    await screen.findByRole("table");
    expect(document.body.textContent).not.toMatch(/fraud|error/i);

    total = 0;
    fireEvent.change(screen.getByLabelText("Status"), {
      target: { value: "reviewed" },
    });
    await screen.findByText("No potential issues.");
    expect(document.body.textContent).not.toMatch(/fraud|error/i);
  });
});

describe("filters", () => {
  test("status and rule send their query strings and reset the page", async () => {
    const fetchMock = mockFetch({
      list: (url) =>
        json(page([LARGE], 120, Number(url.searchParams.get("offset")))),
    });
    renderPage();

    await screen.findByRole("table");
    expect(lastParams(fetchMock)).toEqual({
      status: "open",
      limit: "50",
      offset: "0",
    });

    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    await waitFor(() => {
      expect(lastParams(fetchMock).offset).toBe("50");
    });

    fireEvent.change(screen.getByLabelText("Rule"), {
      target: { value: "possible_duplicate" },
    });
    await waitFor(() => {
      expect(lastParams(fetchMock)).toEqual({
        status: "open",
        rule: "possible_duplicate",
        limit: "50",
        offset: "0",
      });
    });

    fireEvent.change(screen.getByLabelText("Status"), {
      target: { value: "reviewed" },
    });
    await waitFor(() => {
      expect(lastParams(fetchMock).status).toBe("reviewed");
    });

    fireEvent.change(screen.getByLabelText("Status"), {
      target: { value: "" },
    });
    fireEvent.change(screen.getByLabelText("Rule"), {
      target: { value: "" },
    });
    await waitFor(() => {
      expect(lastParams(fetchMock)).toEqual({ limit: "50", offset: "0" });
    });
  });

  test("Previous goes back a page", async () => {
    const fetchMock = mockFetch({
      list: (url) =>
        json(page([LARGE], 120, Number(url.searchParams.get("offset")))),
    });
    renderPage();

    await screen.findByText("1–1 of 120");
    expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    await screen.findByText("51–51 of 120");
    fireEvent.click(screen.getByRole("button", { name: "Previous" }));
    await waitFor(() => {
      expect(lastParams(fetchMock).offset).toBe("0");
    });
  });
});

describe("mark reviewed", () => {
  test("sends one request, disables the button and reloads the table", async () => {
    let reviewed = false;
    let finish: (response: Response) => void = () => undefined;
    const fetchMock = mockFetch({
      list: () => json(reviewed ? page([]) : page([LARGE])),
      review: () =>
        new Promise<Response>((resolve) => {
          finish = resolve;
        }),
    });
    renderPage();

    const button = await screen.findByRole("button", { name: "Mark reviewed" });
    const before = listCalls(fetchMock).length;
    fireEvent.click(button);
    await waitFor(() => {
      expect(button).toBeDisabled();
    });
    fireEvent.click(button);
    expect(reviewCalls(fetchMock)).toHaveLength(1);
    expect(reviewCalls(fetchMock)[0][0]).toBe("/api/anomalies/1/review");

    reviewed = true;
    finish(json(flag({ status: "reviewed" })));

    expect(
      await screen.findByText("No potential issues to review."),
    ).toBeInTheDocument();
    expect(listCalls(fetchMock).length).toBeGreaterThan(before);
  });

  test("a failed review shows the message and keeps the row", async () => {
    mockFetch({
      list: () => json(page([LARGE])),
      review: () => json({ detail: "anomaly flag not found" }, 404),
    });
    renderPage();

    fireEvent.click(
      await screen.findByRole("button", { name: "Mark reviewed" }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "anomaly flag not found",
    );
    expect(
      within(screen.getByRole("table")).getByText("Unusually large expense"),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Mark reviewed" })).toBeEnabled();
  });
});

describe("states", () => {
  test("loading shows the shared Loading", async () => {
    mockFetch({ list: () => json(page([])) });
    renderPage();

    expect(screen.getByRole("status")).toHaveTextContent("Loading…");
    await screen.findByText("No potential issues to review.");
  });

  test("an API error shows the message", async () => {
    mockFetch({ list: () => json({ detail: "database unavailable" }, 503) });
    renderPage();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "database unavailable",
    );
  });

  test("the empty state depends on the status filter", async () => {
    mockFetch({ list: () => json(page([])) });
    renderPage();

    expect(
      await screen.findByText("No potential issues to review."),
    ).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Status"), {
      target: { value: "" },
    });
    expect(await screen.findByText("No potential issues.")).toBeInTheDocument();
  });
});
