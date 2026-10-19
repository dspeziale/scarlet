import { defineConfig, devices } from '@playwright/test';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

// End-to-end tests against the real backend in DEMO mode serving the built UI (npm run build first).
const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const python = process.platform === 'win32' ? 'backend/.venv/Scripts/python' : 'backend/.venv/bin/python';

export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [['list']],
  globalSetup: './e2e/global-setup.ts',
  use: {
    baseURL: 'http://127.0.0.1:8081',
    locale: 'it-IT',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } } }],
  webServer: {
    command: `"${path.join(repo, python)}" -c "import shutil; shutil.rmtree('var/e2e', ignore_errors=True); from pkm.cli import server_main; server_main(['--config', 'config/e2e-demo.yaml'])"`,
    cwd: repo,
    url: 'http://127.0.0.1:8081/readyz',
    reuseExistingServer: false,
    timeout: 60_000,
    env: { PYTHONPATH: 'backend' },
  },
});
