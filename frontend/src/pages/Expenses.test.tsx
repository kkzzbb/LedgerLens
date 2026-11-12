import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, test, vi } from 'vitest'

import type { ExpensesReportResponse } from '../api/types.ts'
import { Expenses } from './Expenses.tsx'

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function report(
  categories: ExpensesReportResponse['categories'],
): ExpensesReportResponse {
  return { from: '2026-01', to: '2026-02', currency: 'EUR', categories }
}

const REPORT = report([
  {
    key: 'groceries',
    name: 'Groceries',
    total: '1334.50',
    months: [
      { month: '2026-01', amount: '1234.50' },
      { month: '2026-02', amount: '100.00' },
    ],
  },
  {
    key: 'rent',
    name: 'Rent',
    total: '1800.00',
    months: [
      { month: '2026-01', amount: '900.00' },
      { month: '2026-02', amount: '900.00' },
    ],
  },
])

function mockFetch(respond: () => Response) {
  const fetchMock = vi.fn((input: string) => {
    void input
    return Promise.resolve(respond())
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function lastUrl(fetchMock: ReturnType<typeof mockFetch>) {
  const calls = fetchMock.mock.calls
  return calls[calls.length - 1][0]
}

function renderPage(today: Date) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  render(
    <QueryClientProvider client={client}>
      <Expenses today={today} />
    </QueryClientProvider>,
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('range', () => {
  test.each([
    [new Date(2026, 6, 15), '2026-02', '2026-07'],
    [new Date(2026, 0, 15), '2025-08', '2026-01'],
  ])('defaults to the last 6 months for %s', async (today, from, to) => {
    const fetchMock = mockFetch(() => json(REPORT))
    renderPage(today)

    expect(screen.getByLabelText('From')).toHaveValue(from)
    expect(screen.getByLabelText('To')).toHaveValue(to)
    await waitFor(() => {
      expect(lastUrl(fetchMock)).toBe(
        `/api/reports/expenses?from=${from}&to=${to}`,
      )
    })
  })

  test('changing From or To refetches with the new range', async () => {
    const fetchMock = mockFetch(() => json(REPORT))
    renderPage(new Date(2026, 6, 15))
    await screen.findByRole('table')

    fireEvent.change(screen.getByLabelText('From'), {
      target: { value: '2026-04' },
    })
    await waitFor(() => {
      expect(lastUrl(fetchMock)).toBe(
        '/api/reports/expenses?from=2026-04&to=2026-07',
      )
    })
    fireEvent.change(screen.getByLabelText('To'), {
      target: { value: '2026-05' },
    })
    await waitFor(() => {
      expect(lastUrl(fetchMock)).toBe(
        '/api/reports/expenses?from=2026-04&to=2026-05',
      )
    })
  })
})

describe('table', () => {
  test('shows categories, months, formatted cells and totals', async () => {
    mockFetch(() => json(REPORT))
    renderPage(new Date(2026, 1, 10))

    const table = await screen.findByRole('table')
    expect(
      within(table)
        .getAllByRole('columnheader')
        .map((th) => th.textContent),
    ).toEqual(['Category', '2026-01', '2026-02', 'Total'])
    expect(
      within(table)
        .getAllByRole('rowheader')
        .map((th) => th.textContent),
    ).toEqual(['Groceries', 'Rent'])
    const groceries = within(table).getAllByRole('row')[1]
    expect(
      within(groceries)
        .getAllByRole('cell')
        .map((td) => td.textContent),
    ).toEqual(['€1,234.50', '€100.00', '€1,334.50'])
  })

  test('all-zero totals show the empty state', async () => {
    mockFetch(() =>
      json(
        report([
          {
            key: 'rent',
            name: 'Rent',
            total: '0.00',
            months: [{ month: '2026-01', amount: '0.00' }],
          },
        ]),
      ),
    )
    renderPage(new Date(2026, 1, 10))

    expect(
      await screen.findByText('No spending in this period.'),
    ).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  test('a 422 shows the detail; loading shows first', async () => {
    mockFetch(() => json({ detail: 'from must not be after to' }, 422))
    renderPage(new Date(2026, 1, 10))

    expect(screen.getByRole('status')).toHaveTextContent('Loading')
    expect(await screen.findByRole('alert')).toHaveTextContent(
      /^from must not be after to$/,
    )
  })
})
