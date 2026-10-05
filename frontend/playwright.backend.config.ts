import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  testMatch: 'backend-playground.spec.ts',
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  use: { baseURL: 'http://127.0.0.1:4175', trace: 'retain-on-failure', screenshot: 'only-on-failure' },
  outputDir: './test-results/backend',
  reporter: [['list'], ['html', { outputFolder: 'playwright-report/backend', open: 'never' }]],
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
    { name: 'firefox', use: { ...devices['Desktop Firefox'] } },
  ],
  webServer: [
    { command: '../.venv/bin/python ../tests/browser_api.py', env: { WEBHDP_BROWSER_TESTING: '1' }, url: 'http://127.0.0.1:4876/__test__/health', reuseExistingServer: false, timeout: 30000 },
    { command: 'npm run dev -- --host 127.0.0.1 --port 4175', env: { VITE_API_URL: 'http://127.0.0.1:4876' }, url: 'http://127.0.0.1:4175', reuseExistingServer: false, timeout: 60000 },
  ],
})
