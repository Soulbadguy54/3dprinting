import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  timeout: 35_000,
  expect: { timeout: 12_000 },
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: process.env.CI ? 'github' : 'list',
  use: {
    baseURL: 'http://127.0.0.1:4173',
    trace: 'retain-on-failure',
  },
  projects: [
    { name: 'Android Chromium', use: { ...devices['Pixel 7'], browserName: 'chromium' } },
    { name: 'iPhone WebKit', use: { ...devices['iPhone 13'], browserName: 'webkit' } },
  ],
  webServer: [
    {
      command: 'python -m uvicorn api.index:app --host 127.0.0.1 --port 8000',
      url: 'http://127.0.0.1:8000/api/health',
      reuseExistingServer: !process.env.CI,
      timeout: 90_000,
    },
    {
      command: 'npm run preview -- --host 127.0.0.1 --port 4173 --strictPort',
      url: 'http://127.0.0.1:4173',
      reuseExistingServer: !process.env.CI,
      timeout: 90_000,
    },
  ],
})
