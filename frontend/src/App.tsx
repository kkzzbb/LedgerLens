import { NavLink, Outlet, Route, Routes } from 'react-router-dom'

import { Alerts } from './pages/Alerts.tsx'
import { Expenses } from './pages/Expenses.tsx'
import { NotFound } from './pages/NotFound.tsx'
import { Overview } from './pages/Overview.tsx'
import { Transactions } from './pages/Transactions.tsx'

const NAV_ITEMS = [
  { to: '/', label: 'Overview' },
  { to: '/transactions', label: 'Transactions' },
  { to: '/expenses', label: 'Expenses' },
  { to: '/alerts', label: 'Alerts' },
]

function Layout() {
  return (
    <>
      <header>
        <p role="note">Demo data from a simulated bank (DemoBank)</p>
        <nav aria-label="Main">
          <ul>
            {NAV_ITEMS.map((item) => (
              <li key={item.to}>
                {/* NavLink sets aria-current="page" on the active link. */}
                <NavLink to={item.to} end>
                  {item.label}
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>
      </header>
      <main>
        <Outlet />
      </main>
    </>
  )
}

// The routes and navigation shell. main.tsx wraps it in the router and the
// TanStack Query provider.
function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Overview />} />
        <Route path="transactions" element={<Transactions />} />
        <Route path="expenses" element={<Expenses />} />
        <Route path="alerts" element={<Alerts />} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  )
}

export default App
