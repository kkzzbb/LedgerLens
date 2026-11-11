// Registers the jest-dom matchers (toBeInTheDocument, ...) on Vitest's
// expect, and their types for tsc.
import '@testing-library/jest-dom/vitest'

import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

// Vitest globals are off, so Testing Library cannot register its own cleanup.
afterEach(() => {
  cleanup()
})
