// Formats a decimal amount string for display. The string goes to
// Intl.NumberFormat as is, so it is never parsed to a (lossy) number.
export function formatMoney(amount: string, currency = 'EUR'): string {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency }).format(
    amount as Intl.StringNumericLiteral,
  )
}
