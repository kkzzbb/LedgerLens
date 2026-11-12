// Response types of the backend API, written by hand from the Pydantic
// models in backend/ledgerlens/api/*.py. Field names stay snake_case.
// Amounts and balances are decimal strings: never parse them to a number.
// Dates and datetimes are ISO 8601 strings.

export interface HealthResponse {
  status: 'ok' | 'degraded'
  database: 'ok' | 'unavailable'
}

export interface AccountResponse {
  id: number
  provider: string
  external_account_id: string
  display_name: string
  currency: string
  last_balance: string | null
  last_balance_at: string | null
  last_sync_at: string | null
  last_sync_status: string | null
  last_sync_error: string | null
  last_successful_sync_at: string | null
}

export interface AccountListResponse {
  accounts: AccountResponse[]
}

export interface TransactionResponse {
  id: number
  account_id: number
  booking_date: string
  value_date: string | null
  amount: string
  currency: string
  direction: string
  counterparty_name: string | null
  counterparty_reference: string | null
  description: string | null
  status: string
}

export interface TransactionListResponse {
  items: TransactionResponse[]
  total: number
  limit: number
  offset: number
}

export interface TransactionParams {
  account_id?: number
  date_from?: string
  date_to?: string
  direction?: 'debit' | 'credit'
  q?: string
  limit?: number
  offset?: number
}

export interface AccountSyncResponse {
  account_id: number
  external_account_id: string
  status: string
  created_count: number
  skipped_count: number
  rejected_count: number
  error: string | null
}

export interface AnomalyRuleResponse {
  rule: string
  created_count: number
  error: string | null
}

export interface SyncResponse {
  accounts: AccountSyncResponse[]
  anomalies: AnomalyRuleResponse[]
}

export interface MonthResponse {
  month: string
  money_in: string
  money_out: string
  net: string
}

export interface MonthlyReportResponse {
  from: string
  to: string
  currency: string
  months: MonthResponse[]
}

export interface MonthAmountResponse {
  month: string
  amount: string
}

export interface CategoryReportResponse {
  key: string
  name: string
  total: string
  months: MonthAmountResponse[]
}

export interface ExpensesReportResponse {
  from: string
  to: string
  currency: string
  categories: CategoryReportResponse[]
}

export interface FlaggedTransactionResponse {
  id: number
  booking_date: string
  counterparty_name: string | null
  amount: string
  category: string | null
}

export interface AnomalyFlagResponse {
  id: number
  rule: string
  status: string
  reason: string
  created_at: string
  reviewed_at: string | null
  transaction: FlaggedTransactionResponse
  related_transaction: FlaggedTransactionResponse | null
}

export interface AnomalyFlagListResponse {
  items: AnomalyFlagResponse[]
  total: number
  limit: number
  offset: number
}

export interface AnomalyParams {
  status?: 'open' | 'reviewed'
  rule?: 'possible_duplicate' | 'large_expense'
  limit?: number
  offset?: number
}
