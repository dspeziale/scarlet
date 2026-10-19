import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import i18n from '@/i18n';
import { ToastProvider } from '@/components/Toasts';
import DeployWizard from '../DeployWizard';
import ImageOnboarding from '../ImageOnboarding';
import { defaultSpec } from '../logic';

vi.mock('@/auth/AuthContext', () => ({
  useAuth: () => ({ can: () => true, user: { username: 'admin', role: 'admin' }, session: null }),
}));
// CodeMirror needs real layout APIs: a textarea is enough for these tests.
vi.mock('@/components/YamlEditor', () => ({
  YamlEditor: ({ value, label }: { value: string; label: string }) => <textarea aria-label={label} readOnly value={value} />,
  YamlDiff: () => null,
  yamlSyntaxErrors: () => [],
}));

type Handler = (url: URL, init?: RequestInit) => unknown;
let routes: Record<string, Handler> = {};
const calls: { path: string; body?: unknown }[] = [];

function json(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), { status, headers: { 'content-type': 'application/json' } });
}

beforeEach(async () => {
  await i18n.changeLanguage('it');
  calls.length = 0;
  routes = {
    '/api/v1/k8s/namespaces': () => ({ items: [{ name: 'default' }, { name: 'prod' }], count: 2 }),
    '/api/v1/k8s/storageclasses': () => ({ items: [{ name: 'standard', default: true }], count: 1 }),
    '/api/v1/deploy/preview': () => ({
      manifests: [],
      yaml: 'apiVersion: apps/v1\nkind: Deployment\n',
      risks: [{ level: 'medium', code: 'no_readiness', params: {} }],
      blocking: [],
      dryRun: [{ kind: 'Deployment', name: 'web', ok: true, existed: false }],
      valid: true,
    }),
  };
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo, init?: RequestInit) => {
      const url = new URL(String(input), 'http://localhost');
      calls.push({ path: url.pathname, body: init?.body ? JSON.parse(String(init.body)) : undefined });
      const h = routes[url.pathname];
      if (!h) return json({ error: { code: 'not_found', message: url.pathname } }, 404);
      return json(h(url, init));
    }),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function wrap(ui: ReactNode, entry: string | { pathname: string; state?: unknown } = '/') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[entry]}>
        <ToastProvider>{ui}</ToastProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('DeployWizard', () => {
  it('walks a prefilled spec to the summary and shows preview risks and dry-run', async () => {
    const user = userEvent.setup();
    const prefill = { ...defaultSpec(), name: 'web', namespace: 'prod', image: 'nginx', tag: '1.27', port: 80 };
    wrap(<DeployWizard />, { pathname: '/operations/deploy', state: { prefill, from: 'onboarding' } });
    expect(screen.getByLabelText('Nome dell\'applicazione')).toHaveValue('web');
    for (let i = 0; i < 10; i++) {
      await user.click(screen.getByRole('button', { name: /Avanti/ }));
    }
    expect(await screen.findByText('Nessuna readiness probe')).toBeInTheDocument();
    expect(screen.getByText('Deployment/web')).toBeInTheDocument();
    const preview = calls.find((c) => c.path === '/api/v1/deploy/preview');
    expect(preview?.body).toMatchObject({ name: 'web', namespace: 'prod', image: 'nginx', tag: '1.27', port: 80 });
    expect(screen.getByRole('button', { name: /Vai al deploy/ })).toBeEnabled();
  });

  it('blocks the first step on an invalid name', async () => {
    const user = userEvent.setup();
    wrap(<DeployWizard />, '/operations/deploy');
    await user.type(screen.getByLabelText('Nome dell\'applicazione'), 'Bad_Name');
    await user.click(screen.getByRole('button', { name: /Avanti/ }));
    expect(await screen.findByText(/Usa minuscole, numeri e '-'/)).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /1\. Nome/ })).toBeInTheDocument();
  });
});

describe('ImageOnboarding', () => {
  it('shows a failed tag check with the fix and blocks the wizard', async () => {
    routes['/api/v1/images/inspect'] = () => ({
      image: 'registry.example.com/shop/worker:9.9',
      checks: [
        { id: 'image_format', status: 'ok', params: { image: 'registry.example.com/shop/worker:9.9' } },
        { id: 'registry_reachable', status: 'ok', params: { registry: 'registry.example.com' } },
        { id: 'registry_auth', status: 'ok', params: {} },
        { id: 'tag_exists', status: 'fail', params: { tag: '9.9' } },
      ],
      config: null,
      risks: [],
    });
    const user = userEvent.setup();
    wrap(<ImageOnboarding />, '/operations/onboarding?image=registry.example.com/shop/worker:9.9');
    expect(screen.getByLabelText("Riferimento dell'immagine")).toHaveValue('registry.example.com/shop/worker:9.9');
    await user.click(screen.getByRole('button', { name: /Verifica immagine/ }));
    expect(await screen.findByText("L'immagine non può essere usata così com'è")).toBeInTheDocument();
    expect(screen.getByText(/Il tag 9.9 non esiste/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Avanti/ })).toBeDisabled();
    const inspect = calls.find((c) => c.path === '/api/v1/images/inspect');
    expect(inspect?.body).toMatchObject({ image: 'registry.example.com/shop/worker:9.9' });
  });

  it('verifies, analyses and hands a prefilled spec to the deploy wizard', async () => {
    routes['/api/v1/images/inspect'] = () => ({
      image: 'nginx:1.27',
      checks: [{ id: 'image_format', status: 'ok', params: {} }, { id: 'tag_exists', status: 'ok', params: { tag: '1.27' } }],
      config: { exposedPorts: [{ port: 80, protocol: 'TCP' }], volumes: [], user: '', runsAsRoot: true, env: [], entrypoint: [], cmd: [] },
      risks: [{ level: 'medium', code: 'runs_as_root' }],
      demo: true,
    });
    const user = userEvent.setup();
    wrap(<ImageOnboarding />, '/operations/onboarding?image=nginx:1.27');
    await user.click(screen.getByRole('button', { name: /Verifica immagine/ }));
    expect(await screen.findByText('Immagine verificata')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /Avanti/ }));
    expect(screen.getByText('Gira come root')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /Avanti/ }));
    expect(screen.getByLabelText("Nome dell'applicazione")).toHaveValue('nginx');
    expect(screen.getByLabelText("Porta dell'applicazione")).toHaveValue(80);
    await user.click(screen.getByRole('button', { name: /Avanti/ }));
    expect(screen.getByRole('button', { name: /Continua nel wizard di deploy/ })).toBeInTheDocument();
  });
});
