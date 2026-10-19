import { useCallback, useEffect, useState, type ReactNode } from 'react';
import { useMutation, useQuery, useQueryClient, type QueryKey, type UseQueryOptions } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { ApiError, api, get, type RequestOptions } from '@/api/client';
import type { Operation, SystemStatus } from '@/api/types';
import { useToast } from '@/components/Toasts';
import { errorMessage } from '@/components/ErrorPanel';

/** GET query bound to the API path; key = [path, query]. */
export function useApi<T>(
  path: string | null,
  query?: RequestOptions['query'],
  opts?: Omit<UseQueryOptions<T, Error, T, QueryKey>, 'queryKey' | 'queryFn'>,
) {
  return useQuery<T, Error>({
    queryKey: [path, query ?? {}],
    queryFn: ({ signal }) => api<T>(path!, { query, signal }),
    enabled: path !== null && (opts?.enabled ?? true),
    ...opts,
  });
}

export function useSystemStatus() {
  return useApi<SystemStatus>('/system/status', undefined, { refetchInterval: 60_000, staleTime: 20_000 });
}

/**
 * Run a state-changing call with a toast on success/error and query invalidation.
 * Returns {run, busy, error}.
 */
export function useAction<A = void, R = unknown>(
  fn: (arg: A) => Promise<R>,
  { success, invalidate = true, onSuccess }: { success?: string | ((r: R) => string); invalidate?: boolean; onSuccess?: (r: R) => void } = {},
) {
  const qc = useQueryClient();
  const toast = useToast();
  const { t } = useTranslation();
  const m = useMutation<R, Error, A>({
    mutationFn: fn,
    onSuccess: (r) => {
      if (success) toast('ok', typeof success === 'function' ? success(r) : success);
      if (invalidate) void qc.invalidateQueries();
      onSuccess?.(r);
    },
    onError: (e) => {
      if (e instanceof ApiError && e.code === 'confirmation_required') return;
      toast('err', errorMessage(e, t));
    },
  });
  return { run: m.mutateAsync, busy: m.isPending, error: m.error, reset: m.reset };
}

/** Polls a background operation until it finishes. */
export function useOperation(id: string | null) {
  return useApi<Operation>(id ? `/operations/${id}` : null, undefined, {
    refetchInterval: (q) => (q.state.data && q.state.data.status !== 'running' ? false : 1000),
  });
}

/** Subscribes to server-sent events; invalidates notification/overview queries when the backend signals changes. */
export function useLiveEvents(enabled: boolean) {
  const qc = useQueryClient();
  useEffect(() => {
    if (!enabled || typeof EventSource === 'undefined') return;
    let es: EventSource | null = null;
    let retry = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let closed = false;
    const connect = () => {
      es = new EventSource('/api/v1/stream', { withCredentials: true });
      es.onmessage = () => {
        retry = 0;
        void qc.invalidateQueries({ queryKey: ['/notifications'] });
        void qc.invalidateQueries({ queryKey: ['/cluster/overview'] });
        void qc.invalidateQueries({ queryKey: ['/cluster/issues'] });
      };
      es.onerror = () => {
        es?.close();
        // Bounded exponential backoff: never a tight reconnect loop.
        if (!closed && retry < 8) timer = setTimeout(connect, Math.min(60_000, 2000 * 2 ** retry++));
      };
    };
    connect();
    return () => {
      closed = true;
      if (timer) clearTimeout(timer);
      es?.close();
    };
  }, [enabled, qc]);
}

export function useDebounced<T>(value: T, ms = 300): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const id = setTimeout(() => setV(value), ms);
    return () => clearTimeout(id);
  }, [value, ms]);
  return v;
}

export function useLocalState<T>(key: string, initial: T): [T, (v: T) => void] {
  const [v, setV] = useState<T>(() => {
    try {
      const raw = localStorage.getItem(key);
      return raw === null ? initial : (JSON.parse(raw) as T);
    } catch {
      return initial;
    }
  });
  const set = useCallback(
    (nv: T) => {
      setV(nv);
      try {
        localStorage.setItem(key, JSON.stringify(nv));
      } catch {
        /* storage unavailable */
      }
    },
    [key],
  );
  return [v, set];
}

export type { ReactNode };
export { get };
