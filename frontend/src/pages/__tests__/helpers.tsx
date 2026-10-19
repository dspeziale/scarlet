import type { ReactElement } from 'react';
import { render } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { vi } from 'vitest';
import { AuthProvider } from '@/auth/AuthContext';
import { ToastProvider } from '@/components/Toasts';

export interface Call {
  method: string;
  path: string;
  body: unknown;
  headers: Record<string, string>;
}

type Handler = (call: Call) => { status?: number; body: unknown } | undefined;

/**
 * Installs a fetch mock routing "METHOD /api/v1/path" (query string ignored) to handlers.
 * A route value is a handler, a `{status, body}` response or a plain 200 body. Returns the call log.
 */
export function mockApi(routes: Record<string, Handler | unknown>): Call[] {
  const calls: Call[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), 'http://localhost');
    const method = (init?.method ?? 'GET').toUpperCase();
    const call: Call = {
      method,
      path: url.pathname.replace(/^\/api\/v1/, ''),
      body: init?.body ? JSON.parse(String(init.body)) : undefined,
      headers: (init?.headers ?? {}) as Record<string, string>,
    };
    calls.push(call);
    const route = routes[`${method} ${call.path}`];
    let res: { status?: number; body: unknown } | undefined;
    const isResponse = (r: unknown): r is { status: number; body: unknown } =>
      !!r && typeof r === 'object' && typeof (r as { status?: unknown }).status === 'number' && 'body' in (r as object);
    if (typeof route === 'function') res = (route as Handler)(call);
    else if (isResponse(route)) res = route;
    else if (route !== undefined) res = { body: route };
    const status = res?.status ?? (res ? 200 : 404);
    const payload = res ? res.body : { error: { code: 'not_found', message: `no mock for ${method} ${call.path}` } };
    return {
      ok: status >= 200 && status < 300,
      status,
      statusText: String(status),
      headers: { get: (h: string) => (h.toLowerCase() === 'content-type' ? 'application/json' : null) },
      json: async () => payload,
      text: async () => JSON.stringify(payload),
    } as unknown as Response;
  });
  vi.stubGlobal('fetch', fetchMock);
  return calls;
}

export function session(role: 'admin' | 'operator' | 'viewer', permissions: string[]) {
  return {
    user: {
      id: 1,
      username: 'admin',
      display_name: '',
      email: '',
      role,
      active: true,
      must_change_password: false,
      language: 'it',
      last_login_at: null,
      created_at: '2026-10-01T00:00:00+00:00',
      locked: false,
    },
    permissions,
    csrfToken: 'csrf-test',
    expiresAt: '2026-10-20T00:00:00+00:00',
  };
}

export function renderPage(ui: ReactElement, { route = '/', path = '*' }: { route?: string; path?: string } = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, refetchInterval: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[route]}>
        <ToastProvider>
          <AuthProvider>
            <Routes>
              <Route path={path} element={ui} />
              <Route path="*" element={<div>other route</div>} />
            </Routes>
          </AuthProvider>
        </ToastProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
