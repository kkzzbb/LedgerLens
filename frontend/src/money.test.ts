import { expect, test } from 'vitest'

import { formatMoney } from './money.ts'

test.each([
  ['1234.5', '€1,234.50'],
  ['-12.00', '-€12.00'],
  ['0.00', '€0.00'],
  // Loses precision as a float: proves the string is not made a Number.
  ['9007199254740993.01', '€9,007,199,254,740,993.01'],
])('formatMoney(%s) is %s', (amount, expected) => {
  expect(formatMoney(amount)).toBe(expected)
})
