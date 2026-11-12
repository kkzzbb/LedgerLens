import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// Node's process global, typed here because @types/node is not installed.
declare const process: { env: Record<string, string | undefined> }

// Where the dev server forwards /api. Read from the Node environment, not a
// VITE_ variable, so it is never exposed to the browser.
const apiProxyTarget = process.env.API_PROXY_TARGET || 'http://localhost:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': { target: apiProxyTarget, changeOrigin: true },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/setupTests.ts'],
  },
})
