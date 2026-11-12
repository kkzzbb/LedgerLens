// A small typed client for the backend API. URLs are relative: the Vite
// dev server proxies /api to the backend, so the browser needs no CORS.
import type {
  AccountListResponse,
  HealthResponse,
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

export function transactionsQuery(params: TransactionParams): string {
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

export function runSync(): Promise<SyncResponse> {
  return request<SyncResponse>('/api/sync', { method: 'POST' })
}
