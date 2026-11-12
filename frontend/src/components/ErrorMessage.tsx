import type { ApiError } from '../api/client.ts'

export function ErrorMessage({ error }: { error: ApiError }) {
  return <p role="alert">{error.message}</p>
}
