import { beforeAll, describe, expect, it } from 'vitest';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import i18n from '@/i18n';
import SettingsPage from '../SettingsPage';
import { mockApi, renderPage, session } from '@/pages/__tests__/helpers';

const e = (value: unknown, source = 'file') => ({ value, source, editable: true });

const SETTINGS = {
  effective: {
    kubernetes: {
      enabled: e(true),
      kubeconfig: e('/etc/pkm/kubeconfig'),
      context: e(null),
      in_cluster: e(false),
      request_timeout: e(20, 'ui'),
      cache_ttl_seconds: e(3),
    },
    monitoring: {
      metrics_server: e(true),
      prometheus_url: e(null),
      prometheus_timeout: e(10),
      prometheus_verify_tls: e(true),
      poll_interval_seconds: e(30),
    },
  },
  editable: { kubernetes: ['enabled', 'kubeconfig'] },
  readonly: {
    mode: 'live',
    environment: 'production',
    configFile: '/etc/pkm/config.yaml',
    server: { host: '0.0.0.0', port: 8443, tls: true, tlsCert: '/etc/pkm/tls/pkm.crt', trustedProxies: [] },
    database: '/var/lib/pkm/pkm.db',
    logFile: null,
    backupDirectory: '/var/lib/pkm/backups',
    cookieSecure: true,
  },
};

const STATUS = {
  appName: 'PKM',
  version: '1.0.0',
  apiVersion: 'v1',
  mode: 'live',
  environment: 'production',
  kubernetes: { connected: true, context: 'prod', server: 'https://k8s:6443', version: 'v1.31.4' },
  podman: { connected: false },
  monitor: { at: null, error: null, issues: 0 },
  prometheus: false,
};

describe('SettingsPage', () => {
  beforeAll(() => i18n.changeLanguage('it'));

  it('sends only the changed keys of the section', async () => {
    const user = userEvent.setup();
    const calls = mockApi({
      'GET /auth/me': session('admin', ['settings.read', 'settings.manage']),
      'GET /settings': SETTINGS,
      'GET /system/status': STATUS,
      'PUT /settings/kubernetes': { effective: {} },
    });
    renderPage(<SettingsPage />, { route: '/settings/kubernetes', path: '/settings/:section' });
    const form = await screen.findByRole('form', { name: 'Connessione a Kubernetes' });
    expect(within(form).getByRole('button', { name: /Salva/ })).toBeDisabled();
    expect(await screen.findByText(/Contesto prod/)).toBeInTheDocument();

    const timeout = within(form).getByLabelText(/Timeout delle richieste/);
    await user.clear(timeout);
    await user.type(timeout, '45');
    await user.click(within(form).getByLabelText(/Contesto/));
    await user.type(within(form).getByLabelText(/Contesto/), 'staging');
    await user.click(within(form).getByRole('button', { name: 'Salva (2 modifiche)' }));

    const put = calls.find((c) => c.method === 'PUT');
    expect(put?.path).toBe('/settings/kubernetes');
    expect(put?.body).toEqual({ request_timeout: 45, context: 'staging' });
    // The monitoring group was untouched: no request for it.
    expect(calls.some((c) => c.path === '/settings/monitoring')).toBe(false);
  });

  it('is read-only without settings.manage', async () => {
    mockApi({
      'GET /auth/me': session('operator', ['settings.read']),
      'GET /settings': SETTINGS,
      'GET /system/status': STATUS,
    });
    renderPage(<SettingsPage />, { route: '/settings/kubernetes', path: '/settings/:section' });
    const form = await screen.findByRole('form', { name: 'Connessione a Kubernetes' });
    expect(within(form).getByLabelText(/Percorso del kubeconfig/)).toBeDisabled();
    expect(within(form).queryByRole('button', { name: /Salva/ })).not.toBeInTheDocument();
  });
});
