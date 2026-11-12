// A small typed client for the backend API. URLs are relative: the Vite
// dev server proxies /api to the backend, so the browser needs no CORS.
import type {
  AccountListResponse,
  AnomalyFlagListResponse,
  AnomalyFlagResponse,
  AnomalyParams,
  ExpensesReportResponse,
  HealthResponse,
  MonthlyReportResponse,
  SyncResponse,
  TransactionListResponse,
  TransactionParams,
} from './types.ts'

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(url, init)
  } catch {
    throw new ApiError(0, 'Network error')
  }
  if (!response.ok) {
    let detail: unknown
    try {
      detail = ((await response.json()) as { detail?: unknown } | null)?.detail
    } catch {
      detail = undefined
    }
    throw new ApiError(
      response.status,
      typeof detail === 'string' ? detail : response.statusText,
    )
  }
  return (await response.json()) as T
}

export function transactionsQuery(
  params: TransactionParams | AnomalyParams,
): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== '') {
      search.append(key, String(value))
    }
  }
  const query = search.toString()
  return query ? `?${query}` : ''
}

export function getHealth(): Promise<HealthResponse> {
  return request<HealthResponse>('/api/health')
}

export function getAccounts(): Promise<AccountListResponse> {
  return request<AccountListResponse>('/api/accounts')
}

export function getTransactions(
  params: TransactionParams = {},
): Promise<TransactionListResponse> {
  return request<TransactionListResponse>(
    `/api/transactions${transactionsQuery(params)}`,
  )
}

export function getAnomalies(
  params: AnomalyParams = {},
): Promise<AnomalyFlagListResponse> {
  return request<AnomalyFlagListResponse>(
    `/api/anomalies${transactionsQuery(params)}`,
  )
}

export function reviewAnomaly(id: number): Promise<AnomalyFlagResponse> {
  return request<AnomalyFlagResponse>(`/api/anomalies/${String(id)}/review`, {
    method: 'POST',
  })
}

export function runSync(): Promise<SyncResponse> {
  return request<SyncResponse>('/api/sync', { method: 'POST' })
}

function monthRange(from: string, to: string): string {
  return new URLSearchParams({ from, to }).toString()
}

export function getMonthlyReport(
  from: string,
  to: string,
): Promise<MonthlyReportResponse> {
  return request<MonthlyReportResponse>(
    `/api/reports/monthly?${monthRange(from, to)}`,
  )
}

export function getExpensesReport(
  from: string,
  to: string,
): Promise<ExpensesReportResponse> {
  return request<ExpensesReportResponse>(
    `/api/reports/expenses?${monthRange(from, to)}`,
  )
}
