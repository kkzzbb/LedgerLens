import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, test } from 'vitest'

import App from './App.tsx'

const BANNER = 'Demo data from a simulated bank (DemoBank)'

function renderAt(path: string) {
  render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  )
}

describe('routes', () => {
  test.each([
    ['/', 'Overview'],
    ['/transactions', 'Transactions'],
    ['/expenses', 'Expenses'],
    ['/alerts', 'Alerts'],
  ])('%s shows its title and the banner', (path, title) => {
    renderAt(path)

    expect(
      screen.getByRole('heading', { level: 1, name: title }),
    ).toBeInTheDocument()
    expect(screen.getByText(BANNER)).toBeInTheDocument()
  })

  test('an unknown path shows "Page not found" with a link to Overview', () => {
    renderAt('/reconciliation')

    expect(
      screen.getByRole('heading', { level: 1, name: 'Page not found' }),
    ).toBeInTheDocument()
    const main = screen.getByRole('main')
    expect(within(main).getByRole('link')).toHaveAttribute('href', '/')
    expect(screen.getByText(BANNER)).toBeInTheDocument()
  })
})

describe('navigation', () => {
  test('lists the four pages in order', () => {
    renderAt('/')

    const nav = screen.getByRole('navigation')
    expect(
      within(nav)
        .getAllByRole('link')
        .map((link) => link.textContent),
    ).toEqual(['Overview', 'Transactions', 'Expenses', 'Alerts'])
  })

  test('marks only the current page with aria-current="page"', () => {
    renderAt('/expenses')

    const nav = screen.getByRole('navigation')
    const current = within(nav)
      .getAllByRole('link')
      .filter((link) => link.getAttribute('aria-current') === 'page')
    expect(current.map((link) => link.textContent)).toEqual(['Expenses'])
  })
})
