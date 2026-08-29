import { defineConfig, devices } from '@playwright/test';

const PORT = Number(process.env.DECK_TEST_PORT || 4319);

export default defineConfig({
  testDir: './specs',
  fullyParallel: true,
  workers: process.env.CI ? 2 : undefined,
  reporter: [['list']],
  // Screenshots land here on purpose, for a human or an agent to look at.
  // Assertions alone missed three real faults; see README.md.
  outputDir: './out/artifacts',
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    viewport: { width: 1440, height: 900 },
    trace: 'retain-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: {
    command: 'node serve.mjs',
    url: `http://127.0.0.1:${PORT}/deck-minted.html`,
    reuseExistingServer: true,
    stdout: 'ignore',
  },
});
