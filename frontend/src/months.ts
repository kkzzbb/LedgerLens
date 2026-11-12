// Month ranges on the local calendar, as YYYY-MM strings.
function monthString(date: Date): string {
  const month = String(date.getMonth() + 1).padStart(2, '0')
  return `${String(date.getFullYear())}-${month}`
}

// The last `count` months up to and including the month of `today`.
export function lastMonths(
  today: Date,
  count: number,
): { from: string; to: string } {
  const first = new Date(today.getFullYear(), today.getMonth() - (count - 1), 1)
  return { from: monthString(first), to: monthString(today) }
}
