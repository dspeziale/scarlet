import { beforeAll, describe, expect, it } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import i18n from '@/i18n';
import SetupWizard from '../SetupWizard';
import { mockApi, renderPage } from '@/pages/__tests__/helpers';

const SYSTEM = {
  checks: [
    { id: 'os', status: 'ok', params: { name: 'Oracle Linux Server 9.7' } },
    { id: 'tls', status: 'warn', params: { enabled: false } },
  ],
  version: '1.0.0',
  config: {
    kubernetes: { enabled: true, kubeconfig: '/etc/pkm/kubeconfig', context: null, in_cluster: false },
    podman: { enabled: true, url: 'unix:///run/podman/podman.sock' },
    monitoring: { prometheus_url: null },
    backup: { directory: '/var/lib/pkm/backups', retention_count: 14 },
    tls: { enabled: false, cert: null },
    server: { host: '0.0.0.0', port: 8443 },
  },
};

describe('SetupWizard', () => {
  beforeAll(() => i18n.changeLanguage('it'));

  it('requires a valid token, sends it as X-Setup-Token and blocks on invalid admin data', async () => {
    const user = userEvent.setup();
    const calls = mockApi({
      'GET /auth/me': { status: 401, body: { error: { code: 'unauthorized', message: 'auth' } } },
      'GET /setup/status': { setupRequired: true, tokenIssued: true, mode: 'live' },
      'POST /setup/verify-token': (c: { headers: Record<string, string> }) =>
        c.headers['X-Setup-Token'] === 'good-token' ? { body: { ok: true } } : { status: 403, body: { error: { code: 'forbidden', message: 'invalid setup token' } } },
      'GET /setup/system-check': SYSTEM,
      'POST /setup/test-kubernetes': { connected: true, context: 'prod', server: 'https://k8s:6443', version: { gitVersion: 'v1.31.4' }, permissions: { nodes: 'ok', pods: 'k8s_forbidden' } },
    });
    renderPage(<SetupWizard />, { route: '/setup', path: '/setup' });

    expect(await screen.findByRole('heading', { name: 'Benvenuto' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Avanti' }));
    expect(screen.getByRole('heading', { name: 'Verifica sistema' })).toBeInTheDocument();
    // Cannot continue without the token.
    expect(screen.getByRole('button', { name: 'Avanti' })).toBeDisabled();

    await user.type(screen.getByLabelText('Token di installazione'), 'wrong');
    await user.click(screen.getByRole('button', { name: /Verifica token/ }));
    expect(await screen.findByText(/Token non valido/)).toBeInTheDocument();

    await user.clear(screen.getByLabelText('Token di installazione'));
    await user.type(screen.getByLabelText('Token di installazione'), 'good-token');
    await user.click(screen.getByRole('button', { name: /Verifica token/ }));
    expect(await screen.findByText('Oracle Linux Server 9.7: supportato.')).toBeInTheDocument();
    const sysCall = calls.find((c) => c.path === '/setup/system-check');
    expect(sysCall?.headers['X-Setup-Token']).toBe('good-token');
    expect(screen.getByRole('button', { name: 'Avanti' })).toBeEnabled();

    // Kubernetes step: the test call carries the token and shows the probe results.
    await user.click(screen.getByRole('button', { name: 'Avanti' }));
    expect(screen.getByRole('heading', { name: /Kubernetes/ })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /Testa la connessione/ }));
    expect(await screen.findByText(/Kubernetes v1.31.4/)).toBeInTheDocument();
    expect(calls.find((c) => c.path === '/setup/test-kubernetes')?.headers['X-Setup-Token']).toBe('good-token');
    expect(calls.find((c) => c.path === '/setup/test-kubernetes')?.body).toMatchObject({ kubeconfig: '/etc/pkm/kubeconfig', context: null });

    // Podman (optional) -> Authentication: Next is blocked until the admin data is valid.
    await user.click(screen.getByRole('button', { name: 'Avanti' }));
    await user.click(screen.getByRole('button', { name: 'Avanti' }));
    expect(screen.getByRole('heading', { name: 'Autenticazione' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Avanti' })).toBeDisabled();
    await user.type(screen.getByLabelText('Password'), 'Short1!');
    expect(screen.getByText('Almeno 12 caratteri.')).toBeInTheDocument();
    await user.clear(screen.getByLabelText('Password'));
    await user.type(screen.getByLabelText('Password'), 'Very-Strong-Pass-42');
    await user.type(screen.getByLabelText('Ripeti la password'), 'Very-Strong-Pass-42');
    await waitFor(() => expect(screen.getByRole('button', { name: 'Avanti' })).toBeEnabled());
  });

  it('shows "already configured" when setup is not required', async () => {
    mockApi({
      'GET /auth/me': { status: 401, body: { error: { code: 'unauthorized', message: 'auth' } } },
      'GET /setup/status': { setupRequired: false, tokenIssued: false, mode: 'live' },
    });
    renderPage(<SetupWizard />, { route: '/setup', path: '/setup' });
    expect(await screen.findByText('Applicazione già configurata')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: "Vai all'accesso" })).toHaveAttribute('href', '/login');
  });
});
