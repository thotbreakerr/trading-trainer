import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:8000',
    },
  },
  // Pure-logic tests only (no jsdom): api client, chart math, manifests.
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts'],
  },
})
