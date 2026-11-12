import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'

import { ApiError, getExpensesReport } from '../api/client.ts'
import type { ExpensesReportResponse } from '../api/types.ts'
import { EmptyState } from '../components/EmptyState.tsx'
import { ErrorMessage } from '../components/ErrorMessage.tsx'
import { Loading } from '../components/Loading.tsx'
import { formatMoney } from '../money.ts'
import { lastMonths } from '../months.ts'

const DEFAULT_MONTHS = 6

function toApiError(error: Error): ApiError {
  return error instanceof ApiError ? error : new ApiError(0, error.message)
}

function ExpensesTable({ report }: { report: ExpensesReportResponse }) {
  const months = report.categories[0]?.months.map((m) => m.month) ?? []
  return (
    <table>
      <thead>
        <tr>
          <th scope="col">Category</th>
          {months.map((month) => (
            <th key={month} scope="col">
              {month}
            </th>
          ))}
          <th scope="col">Total</th>
        </tr>
      </thead>
      <tbody>
        {report.categories.map((category) => (
          <tr key={category.key}>
            <th scope="row">{category.name}</th>
            {category.months.map((m) => (
              <td key={m.month}>{formatMoney(m.amount, report.currency)}</td>
            ))}
            <td>{formatMoney(category.total, report.currency)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

export function Expenses({ today = new Date() }: { today?: Date }) {
  const [range, setRange] = useState(() => lastMonths(today, DEFAULT_MONTHS))

  const report = useQuery({
    queryKey: ['reports', 'expenses', range.from, range.to],
    queryFn: () => getExpensesReport(range.from, range.to),
    retry: false,
  })

  let content
  if (report.isPending) {
    content = <Loading />
  } else if (report.isError) {
    content = <ErrorMessage error={toApiError(report.error)} />
  } else if (report.data.categories.every((c) => c.total === '0.00')) {
    content = <EmptyState message="No spending in this period." />
  } else {
    content = <ExpensesTable report={report.data} />
  }

  return (
    <>
      <h1>Expenses</h1>
      <div>
        <label>
          From
          <input
            type="month"
            value={range.from}
            onChange={(event) => {
              setRange({ ...range, from: event.target.value })
            }}
          />
        </label>
        <label>
          To
          <input
            type="month"
            value={range.to}
            onChange={(event) => {
              setRange({ ...range, to: event.target.value })
            }}
          />
        </label>
      </div>
      {content}
    </>
  )
}
