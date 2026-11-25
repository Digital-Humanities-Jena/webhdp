import { defineConfig, devices } from '@playwright/test'

const baseURL = 'http://127.0.0.1:4177'

export default defineConfig({
  testDir: './e2e',
  testMatch: 'iiif-presentation.spec.ts',
  projects: [
    { name: 'chromium-csp', use: { ...devices['Desktop Chrome'] } },
    { name: 'firefox-csp', use: { ...devices['Desktop Firefox'] } },
  ],
  workers: 1,
  use: { baseURL, trace: 'retain-on-failure' },
  outputDir: './test-results/iiif-csp',
  webServer: {
    command: 'npm run build -- --logLevel warn && npm run preview -- --host 127.0.0.1 --port 4177 --strictPort',
    env: { VITE_API_URL: '/api/v1' },
    url: baseURL,
    reuseExistingServer: false,
    timeout: 60_000,
  },
})
