import { useQuery } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'

import { ApiError, getTransactions } from '../api/client.ts'
import type { TransactionParams, TransactionResponse } from '../api/types.ts'
import { EmptyState } from '../components/EmptyState.tsx'
import { ErrorMessage } from '../components/ErrorMessage.tsx'
import { Loading } from '../components/Loading.tsx'
import { formatMoney } from '../money.ts'

const PAGE_SIZE = 50

type Direction = '' | 'debit' | 'credit'

interface Filters {
  dateFrom: string
  dateTo: string
  direction: Direction
  q: string
}

const NO_FILTERS: Filters = { dateFrom: '', dateTo: '', direction: '', q: '' }

// Amounts are always positive strings; the direction carries the sign.
function signedAmount(tx: TransactionResponse): string {
  const amount = tx.direction === 'debit' ? `-${tx.amount}` : tx.amount
  return formatMoney(amount, tx.currency)
}

export function Transactions() {
  const [filters, setFilters] = useState<Filters>(NO_FILTERS)
  const [searchInput, setSearchInput] = useState('')
  const [offset, setOffset] = useState(0)

  // Empty values are dropped from the query string by getTransactions.
  const params: TransactionParams = {
    date_from: filters.dateFrom || undefined,
    date_to: filters.dateTo || undefined,
    direction: filters.direction || undefined,
    q: filters.q || undefined,
    limit: PAGE_SIZE,
    offset,
  }

  const query = useQuery({
    queryKey: ['transactions', params],
    queryFn: () => getTransactions(params),
    retry: false,
  })

  function updateFilters(change: Partial<Filters>) {
    setFilters((current) => ({ ...current, ...change }))
    setOffset(0)
  }

  function submitSearch(event: FormEvent) {
    event.preventDefault()
    updateFilters({ q: searchInput.trim() })
  }

  function clearFilters() {
    setFilters(NO_FILTERS)
    setSearchInput('')
    setOffset(0)
  }

  const hasFilters = Object.values(filters).some((value) => value !== '')

  let content
  if (query.isPending) {
    content = <Loading />
  } else if (query.isError) {
    const error =
      query.error instanceof ApiError
        ? query.error
        : new ApiError(0, query.error.message)
    content = <ErrorMessage error={error} />
  } else if (query.data.total === 0) {
    content = hasFilters ? (
      <>
        <EmptyState message="No transactions match these filters" />
        <button type="button" onClick={clearFilters}>
          Clear filters
        </button>
      </>
    ) : (
      <EmptyState message="No transactions yet. Run a sync to import them." />
    )
  } else {
    const { items, total } = query.data
    const first = offset + 1
    const last = offset + items.length
    content = (
      <>
        <table>
          <thead>
            <tr>
              <th scope="col">Date</th>
              <th scope="col">Counterparty</th>
              <th scope="col">Description</th>
              <th scope="col">Amount</th>
            </tr>
          </thead>
          <tbody>
            {items.map((tx) => (
              <tr key={tx.id}>
                <td>{tx.booking_date}</td>
                <td>{tx.counterparty_name ?? '—'}</td>
                <td>{tx.description ?? '—'}</td>
                <td>{signedAmount(tx)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <nav aria-label="Pagination">
          <button
            type="button"
            disabled={offset === 0}
            onClick={() => {
              setOffset(Math.max(0, offset - PAGE_SIZE))
            }}
          >
            Previous
          </button>
          <span>
            {first}–{last} of {total}
          </span>
          <button
            type="button"
            disabled={offset + PAGE_SIZE >= total}
            onClick={() => {
              setOffset(offset + PAGE_SIZE)
            }}
          >
            Next
          </button>
        </nav>
      </>
    )
  }

  return (
    <>
      <h1>Transactions</h1>
      <div>
        <label>
          From{' '}
          <input
            type="date"
            value={filters.dateFrom}
            onChange={(event) => {
              updateFilters({ dateFrom: event.target.value })
            }}
          />
        </label>
        <label>
          To{' '}
          <input
            type="date"
            value={filters.dateTo}
            onChange={(event) => {
              updateFilters({ dateTo: event.target.value })
            }}
          />
        </label>
        <label>
          Direction{' '}
          <select
            value={filters.direction}
            onChange={(event) => {
              updateFilters({ direction: event.target.value as Direction })
            }}
          >
            <option value="">All</option>
            <option value="credit">Money in</option>
            <option value="debit">Money out</option>
          </select>
        </label>
        <form role="search" onSubmit={submitSearch}>
          <label>
            Search{' '}
            <input
              type="search"
              value={searchInput}
              onChange={(event) => {
                setSearchInput(event.target.value)
              }}
            />
          </label>
          <button type="submit">Search</button>
        </form>
      </div>
      {content}
    </>
  )
}
