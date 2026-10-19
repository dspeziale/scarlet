import { request } from '@playwright/test';

export const ADMIN = { username: 'admin', password: 'E2e-Sup3r-Pass-2026!' };
export const VIEWER = { username: 'viewer1', password: 'E2e-Read0nly-Pass-2026!' };

/** Creates the administrator through the first-run API (setup token read via pkm-admin) and a viewer. */
export default async function globalSetup() {
  const { execFileSync } = await import('node:child_process');
  const path = await import('node:path');
  const { fileURLToPath } = await import('node:url');
  const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
  const python = process.platform === 'win32' ? 'backend/.venv/Scripts/python' : 'backend/.venv/bin/python';
  const api = await request.newContext({ baseURL: 'http://127.0.0.1:8081' });
  const info = await (await api.get('/api/v1/system/info')).json();
  if (info.setupRequired) {
    const token = execFileSync(
      path.join(repo, python),
      ['-c', "from pkm.cli import admin_main; admin_main(['--config', 'config/e2e-demo.yaml', 'setup-token'])"],
      { cwd: repo, env: { ...process.env, PYTHONPATH: 'backend' } },
    )
      .toString()
      .trim();
    const res = await api.post('/api/v1/setup/complete', {
      headers: { 'X-Setup-Token': token },
      data: { admin: { username: ADMIN.username, password: ADMIN.password, display_name: 'E2E Admin' }, language: 'it' },
    });
    if (!res.ok()) throw new Error(`setup failed: ${res.status()} ${await res.text()}`);
  }
  const login = await api.post('/api/v1/auth/login', { data: ADMIN });
  const { csrfToken } = await login.json();
  const users = await (await api.get('/api/v1/users')).json();
  if (!users.items.some((u: { username: string }) => u.username === VIEWER.username)) {
    const r = await api.post('/api/v1/users', {
      headers: { 'X-CSRF-Token': csrfToken },
      data: { ...VIEWER, role: 'viewer', must_change_password: false, language: 'it' },
    });
    if (!r.ok()) throw new Error(`viewer creation failed: ${await r.text()}`);
  }
  await api.dispose();
}
