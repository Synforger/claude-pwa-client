import { defineConfig, devices } from '@playwright/test'

const BASE_URL = process.env.CPC_E2E_BASE_URL || 'http://127.0.0.1:18765'
const KEEP_BACKEND = process.env.CPC_E2E_KEEP_BACKEND === '1'

export default defineConfig({
  testDir: './scenarios',
  outputDir: './test-results',
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  // Some scenarios reseed the shared ses_e2echatgld fixture and the backend
  // status SSE briefly serves the stale snapshot during the swap. A single
  // retry papers over that transient race without masking a real failure
  // (= a true bug stays red on both attempts).
  retries: 1,
  workers: 1,
  reporter: [['list'], ['html', { outputFolder: 'playwright-report', open: 'never' }]],

  globalSetup: './helpers/global-setup.js',
  globalTeardown: './helpers/global-teardown.js',

  use: {
    baseURL: BASE_URL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    actionTimeout: 10_000,
    navigationTimeout: 30_000,
  },

  expect: {
    timeout: 10_000,
  },

  projects: [
    {
      name: 'chromium-desktop',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1280, height: 800 } },
    },
    {
      name: 'webkit-mobile',
      use: { ...devices['iPhone 14'] },
    },
  ],

  webServer: KEEP_BACKEND ? undefined : {
    command: 'node ./helpers/run-backend.mjs',
    url: `${BASE_URL}/healthz`,
    reuseExistingServer: false,
    stdout: 'pipe',
    stderr: 'pipe',
    timeout: 90_000,
  },
})
