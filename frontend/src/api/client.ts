// HTTP client for the PKM REST API (/api/v1).
// The browser never talks to Kubernetes or Podman directly: only to this backend.

export const API_BASE = '/api/v1';

export interface ApiErrorBody {
  code: string;
  message: string;
  params?: Record<string, unknown>;
  details?: string | null;
  requestId?: string | null;
}

export class ApiError extends Error {
  status: number;
  code: string;
  params: Record<string, unknown>;
  details?: string | null;
  requestId?: string | null;

  constructor(status: number, body: ApiErrorBody) {
    super(body.message);
    this.status = status;
    this.code = body.code;
    this.params = body.params ?? {};
    this.details = body.details;
    this.requestId = body.requestId;
  }
}

let csrfToken: string | null = null;
let onUnauthorized: (() => void) | null = null;

export function setCsrfToken(token: string | null): void {
  csrfToken = token;
}

export function setUnauthorizedHandler(fn: (() => void) | null): void {
  onUnauthorized = fn;
}

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  body?: unknown;
  query?: Record<string, string | number | boolean | null | undefined>;
  headers?: Record<string, string>;
  signal?: AbortSignal;
  timeoutMs?: number;
}

export function buildUrl(path: string, query?: RequestOptions['query']): string {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(query ?? {})) {
    if (v !== undefined && v !== null && v !== '') qs.set(k, String(v));
  }
  const s = qs.toString();
  return `${API_BASE}${path}${s ? `?${s}` : ''}`;
}

export async function api<T = unknown>(path: string, opts: RequestOptions = {}): Promise<T> {
  const method = opts.method ?? 'GET';
  const headers: Record<string, string> = { Accept: 'application/json', ...(opts.headers ?? {}) };
  if (opts.body !== undefined) headers['Content-Type'] = 'application/json';
  if (method !== 'GET' && csrfToken) headers['X-CSRF-Token'] = csrfToken;

  // Every request has a timeout: a slow API must never freeze the UI.
  const ctrl = new AbortController();
  const timeout = setTimeout(() => ctrl.abort(new DOMException('timeout', 'TimeoutError')), opts.timeoutMs ?? 45000);
  opts.signal?.addEventListener('abort', () => ctrl.abort(opts.signal?.reason));
  let res: Response;
  try {
    res = await fetch(buildUrl(path, opts.query), {
      method,
      headers,
      body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
      credentials: 'same-origin',
      signal: ctrl.signal,
    });
  } catch (e) {
    const timedOut = e instanceof DOMException && (e.name === 'TimeoutError' || ctrl.signal.reason?.name === 'TimeoutError');
    if (opts.signal?.aborted) throw e;
    throw new ApiError(0, {
      code: timedOut ? 'client_timeout' : 'network_error',
      message: timedOut ? 'request timed out' : 'the server cannot be reached',
      details: String(e),
    });
  } finally {
    clearTimeout(timeout);
  }
  if (res.status === 204) return undefined as T;
  const ctype = res.headers.get('content-type') ?? '';
  const data = ctype.includes('application/json') ? await res.json().catch(() => null) : await res.text();
  if (!res.ok) {
    const body: ApiErrorBody =
      data && typeof data === 'object' && 'error' in data
        ? (data as { error: ApiErrorBody }).error
        : { code: `http_${res.status}`, message: typeof data === 'string' ? data.slice(0, 300) : res.statusText };
    const err = new ApiError(res.status, body);
    // /auth/* answers 401 as part of the normal sign-in flow: only other endpoints mean "session expired".
    if (res.status === 401 && onUnauthorized && !path.startsWith('/auth/')) onUnauthorized();
    throw err;
  }
  return data as T;
}

export const get = <T>(path: string, query?: RequestOptions['query']) => api<T>(path, { query });
export const post = <T>(path: string, body?: unknown, query?: RequestOptions['query']) =>
  api<T>(path, { method: 'POST', body: body ?? {}, query });
export const put = <T>(path: string, body?: unknown) => api<T>(path, { method: 'PUT', body: body ?? {} });
export const patch = <T>(path: string, body?: unknown) => api<T>(path, { method: 'PATCH', body: body ?? {} });
export const del = <T>(path: string, query?: RequestOptions['query']) => api<T>(path, { method: 'DELETE', query });

/** Trigger a browser download of an API resource (cookies are sent automatically). */
export function downloadUrl(path: string, query?: RequestOptions['query']): void {
  const a = document.createElement('a');
  a.href = buildUrl(path, query);
  a.rel = 'noopener';
  document.body.appendChild(a);
  a.click();
  a.remove();
}

/** Resource path helper: cluster-scoped kinds use "_" as namespace. */
export function resPath(kind: string, namespace: string | null | undefined, name: string): string {
  return `/k8s/${kind}/${encodeURIComponent(namespace || '_')}/${encodeURIComponent(name)}`;
}
