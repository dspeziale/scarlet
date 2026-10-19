import { beforeAll, describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import i18n from '@/i18n';
import Health from '../Health';
import { mockApi, renderPage, session } from '@/pages/__tests__/helpers';

describe('Health page', () => {
  beforeAll(() => i18n.changeLanguage('it'));

  it('renders the overall state and each check with translated messages and fix links', async () => {
    mockApi({
      'GET /auth/me': session('viewer', ['monitoring.read']),
      'GET /health': {
        status: 'unhealthy',
        checkedAt: '2026-10-19T10:00:00+00:00',
        checks: [
          { id: 'database', status: 'healthy', message: 'ok', params: { schemaVersion: 1, path: '/var/lib/pkm/pkm.db' }, optional: false, latencyMs: 2 },
          { id: 'kubernetes', status: 'unhealthy', message: 'cannot reach the Kubernetes API', params: { code: 'k8s_unavailable' }, optional: false, latencyMs: 5003 },
          { id: 'prometheus', status: 'degraded', message: 'not_configured', params: {}, optional: true, latencyMs: 0 },
        ],
      },
    });
    renderPage(<Health />);
    expect(await screen.findByText(/Stato generale: Unhealthy/)).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Database' })).toBeInTheDocument();
    expect(screen.getByText('/var/lib/pkm/pkm.db')).toBeInTheDocument();
    // Raw message is kept when no translation exists; known codes are translated.
    expect(screen.getByText('cannot reach the Kubernetes API')).toBeInTheDocument();
    expect(screen.getByText('Non configurato')).toBeInTheDocument();
    expect(screen.getByText('opzionale')).toBeInTheDocument();
    expect(screen.getByText('Healthy')).toBeInTheDocument();
    expect(screen.getByText('Degraded')).toBeInTheDocument();
    const links = screen.getAllByRole('link', { name: 'Come intervenire' });
    expect(links.map((l) => l.getAttribute('href'))).toEqual(['/settings/kubernetes', '/settings/kubernetes']);
  });
});
