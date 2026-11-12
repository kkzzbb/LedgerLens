import { expect, test } from 'vitest'

import { lastMonths } from './months.ts'

test.each([
  [new Date(2026, 6, 31), 6, { from: '2026-02', to: '2026-07' }],
  [new Date(2026, 0, 15), 6, { from: '2025-08', to: '2026-01' }],
  [new Date(2026, 11, 1), 1, { from: '2026-12', to: '2026-12' }],
])('lastMonths(%s, %i) is %o', (today, count, expected) => {
  expect(lastMonths(today, count)).toEqual(expected)
})
