import { afterEach, describe, expect, test, vi } from 'vitest'

import {
  ApiError,
  getAccounts,
  getHealth,
  getTransactions,
  runSync,
} from './client.ts'

function mockFetch(response: Response | Error) {
  const fetchMock = vi.fn(() =>
    response instanceof Error
      ? Promise.reject(response)
      : Promise.resolve(response),
  )
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function json(body: unknown, status = 200, statusText = 'OK') {
  return new Response(JSON.stringify(body), {
    status,
    statusText,
    headers: { 'Content-Type': 'application/json' },
  })
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('endpoints', () => {
  test('call the backend with relative URLs and return the body', async () => {
    const health = { status: 'ok', database: 'ok' }
    let fetchMock = mockFetch(json(health))
    expect(await getHealth()).toEqual(health)
    expect(fetchMock).toHaveBeenCalledWith('/api/health', undefined)

    fetchMock = mockFetch(json({ accounts: [] }))
    expect(await getAccounts()).toEqual({ accounts: [] })
    expect(fetchMock).toHaveBeenCalledWith('/api/accounts', undefined)

    fetchMock = mockFetch(json({ accounts: [] }))
    expect(await runSync()).toEqual({ accounts: [] })
    expect(fetchMock).toHaveBeenCalledWith('/api/sync', { method: 'POST' })
  })
})

describe('getTransactions query string', () => {
  test('sends no query string when no param is set', async () => {
    const fetchMock = mockFetch(json({ items: [], total: 0, limit: 50, offset: 0 }))
    await getTransactions({})
    expect(fetchMock).toHaveBeenCalledWith('/api/transactions', undefined)
  })

  test('sends only the set params, URL-encoded', async () => {
    const fetchMock = mockFetch(json({ items: [], total: 0, limit: 50, offset: 0 }))
    await getTransactions({
      account_id: 3,
      date_from: '2026-01-01',
      date_to: undefined,
      direction: 'debit',
      q: 'café & co/1',
      limit: 20,
      offset: 0,
    })
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/transactions?account_id=3&date_from=2026-01-01&direction=debit' +
        '&q=caf%C3%A9+%26+co%2F1&limit=20&offset=0',
      undefined,
    )
  })
})

describe('ApiError mapping', () => {
  test('uses a string detail as the message', async () => {
    mockFetch(json({ detail: 'The bank is down' }, 502, 'Bad Gateway'))
    await expect(runSync()).rejects.toEqual(
      expect.objectContaining({ status: 502, message: 'The bank is down' }),
    )
  })

  test('uses the status text when detail is a list (422)', async () => {
    mockFetch(
      json(
        { detail: [{ loc: ['query', 'limit'], msg: 'too big' }] },
        422,
        'Unprocessable Entity',
      ),
    )
    const error = await getTransactions({ limit: 999 }).catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({ status: 422, message: 'Unprocessable Entity' })
  })

  test('maps a network failure to status 0 and "Network error"', async () => {
    mockFetch(new TypeError('Failed to fetch'))
    const error = await getHealth().catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({ status: 0, message: 'Network error' })
  })
})
