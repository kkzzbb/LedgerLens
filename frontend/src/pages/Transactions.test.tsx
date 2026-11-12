import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, test, vi } from 'vitest'

import type {
  TransactionListResponse,
  TransactionResponse,
} from '../api/types.ts'
import { Transactions } from './Transactions.tsx'

function tx(overrides: Partial<TransactionResponse>): TransactionResponse {
  return {
    id: 1,
    account_id: 1,
    booking_date: '2026-03-02',
    value_date: null,
    amount: '12.50',
    currency: 'EUR',
    direction: 'debit',
    counterparty_name: null,
    counterparty_reference: null,
    description: null,
    status: 'booked',
    ...overrides,
  }
}

function page(
  items: TransactionResponse[],
  total = items.length,
  offset = 0,
): TransactionListResponse {
  return { items, total, limit: 50, offset }
}

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

// Every call answers with the body built from the requested URL.
function mockFetch(respond: (url: URL) => Response | Promise<Response>) {
  const fetchMock = vi.fn((input: string) =>
    Promise.resolve(respond(new URL(input, 'http://localhost'))),
  )
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function lastParams(fetchMock: ReturnType<typeof mockFetch>) {
  const calls = fetchMock.mock.calls
  const url = calls[calls.length - 1][0]
  return Object.fromEntries(new URL(url, 'http://localhost').searchParams)
}

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <Transactions />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('rows', () => {
  test('shows the columns and signed, formatted amounts in API order', async () => {
    mockFetch(() =>
      json(
        page([
          tx({
            id: 2,
            booking_date: '2026-03-05',
            amount: '1200.00',
            direction: 'credit',
            counterparty_name: 'Acme GmbH',
            description: 'Invoice 42',
          }),
          tx({ id: 1, booking_date: '2026-03-02', amount: '12.50' }),
        ]),
      ),
    )
    renderPage()

    const table = await screen.findByRole('table')
    expect(
      screen.getByRole('heading', { level: 1, name: 'Transactions' }),
    ).toBeInTheDocument()
    expect(
      within(table)
        .getAllByRole('columnheader')
        .map((th) => th.textContent),
    ).toEqual(['Date', 'Counterparty', 'Description', 'Amount'])
    const rows = within(table).getAllByRole('row').slice(1)
    expect(
      rows.map((row) =>
        within(row)
          .getAllByRole('cell')
          .map((td) => td.textContent),
      ),
    ).toEqual([
      ['2026-03-05', 'Acme GmbH', 'Invoice 42', '€1,200.00'],
      ['2026-03-02', '—', '—', '-€12.50'],
    ])
  })
})

describe('filters', () => {
  test('sends filters and the submitted search, and resets the offset', async () => {
    const fetchMock = mockFetch(() => json(page([tx({})], 120)))
    renderPage()

    await screen.findByRole('table')
    expect(lastParams(fetchMock)).toEqual({ limit: '50', offset: '0' })

    fireEvent.click(screen.getByRole('button', { name: 'Next' }))
    await screen.findByText('51–51 of 120')
    expect(lastParams(fetchMock).offset).toBe('50')

    fireEvent.change(screen.getByLabelText('From'), {
      target: { value: '2026-01-01' },
    })
    fireEvent.change(screen.getByLabelText('To'), {
      target: { value: '2026-01-31' },
    })
    fireEvent.change(screen.getByLabelText('Direction'), {
      target: { value: 'debit' },
    })
    await screen.findByRole('table')
    expect(lastParams(fetchMock)).toEqual({
      date_from: '2026-01-01',
      date_to: '2026-01-31',
      direction: 'debit',
      limit: '50',
      offset: '0',
    })

    const callsBefore = fetchMock.mock.calls.length
    fireEvent.change(screen.getByRole('searchbox', { name: 'Search' }), {
      target: { value: 'acme' },
    })
    expect(fetchMock.mock.calls.length).toBe(callsBefore)

    fireEvent.click(screen.getByRole('button', { name: 'Search' }))
    await screen.findByRole('table')
    expect(lastParams(fetchMock)).toMatchObject({ q: 'acme', offset: '0' })
  })
})

describe('paging', () => {
  test('Next and Previous move by 50 and are disabled at the ends', async () => {
    const fetchMock = mockFetch((url) => {
      const offset = Number(url.searchParams.get('offset'))
      const count = Math.min(50, 120 - offset)
      const items = Array.from({ length: count }, (_, i) =>
        tx({ id: offset + i + 1 }),
      )
      return json(page(items, 120, offset))
    })
    renderPage()

    await screen.findByText('1–50 of 120')
    const previous = screen.getByRole('button', { name: 'Previous' })
    expect(previous).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Next' })).toBeEnabled()

    fireEvent.click(screen.getByRole('button', { name: 'Next' }))
    await screen.findByText('51–100 of 120')
    fireEvent.click(screen.getByRole('button', { name: 'Next' }))
    await screen.findByText('101–120 of 120')
    expect(lastParams(fetchMock).offset).toBe('100')
    expect(screen.getByRole('button', { name: 'Next' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Previous' })).toBeEnabled()

    fireEvent.click(screen.getByRole('button', { name: 'Previous' }))
    await screen.findByText('51–100 of 120')
    await waitFor(() => {
      expect(lastParams(fetchMock).offset).toBe('50')
    })
  })
})

describe('empty states', () => {
  test('without filters it asks for a sync', async () => {
    mockFetch(() => json(page([])))
    renderPage()

    expect(
      await screen.findByText('No transactions yet. Run a sync to import them.'),
    ).toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: 'Clear filters' }),
    ).not.toBeInTheDocument()
  })

  test('with filters it offers to clear them', async () => {
    const fetchMock = mockFetch(() => json(page([])))
    renderPage()
    await screen.findByText('No transactions yet. Run a sync to import them.')

    fireEvent.change(screen.getByLabelText('Direction'), {
      target: { value: 'credit' },
    })
    fireEvent.change(screen.getByRole('searchbox', { name: 'Search' }), {
      target: { value: 'nothing' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Search' }))
    expect(
      await screen.findByText('No transactions match these filters'),
    ).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Clear filters' }))
    await screen.findByText('No transactions yet. Run a sync to import them.')
    await waitFor(() => {
      expect(lastParams(fetchMock)).toEqual({ limit: '50', offset: '0' })
    })
    expect(screen.getByRole('searchbox', { name: 'Search' })).toHaveValue('')
    expect(screen.getByLabelText('Direction')).toHaveValue('')
  })
})

describe('errors', () => {
  test('shows the API message and keeps the filters usable', async () => {
    const fetchMock = mockFetch((url) =>
      url.searchParams.has('date_from')
        ? json({ detail: 'date_from must not be after date_to' }, 422)
        : json(page([tx({})])),
    )
    renderPage()
    await screen.findByRole('table')

    fireEvent.change(screen.getByLabelText('From'), {
      target: { value: '2026-02-01' },
    })
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'date_from must not be after date_to',
    )

    fireEvent.change(screen.getByLabelText('From'), { target: { value: '' } })
    await screen.findByRole('table')
    await waitFor(() => {
      expect(lastParams(fetchMock)).toEqual({ limit: '50', offset: '0' })
    })
  })

  test('shows a network error', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.reject(new TypeError('failed'))),
    )
    renderPage()

    expect(await screen.findByRole('alert')).toHaveTextContent('Network error')
  })
})
