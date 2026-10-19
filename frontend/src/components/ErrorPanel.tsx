import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { RefreshCw } from 'lucide-react';
import { ApiError } from '@/api/client';
import { Alert } from './ui';

/**
 * Explains an error in plain language: what happened, the probable cause and what to do,
 * with the raw technical details available on demand. Never just "500".
 */
export function ErrorPanel({ error, onRetry, context }: { error: unknown; onRetry?: () => void; context?: string }) {
  const { t, i18n } = useTranslation('errors');
  const e = error instanceof ApiError ? error : null;
  const code = e?.code ?? 'unknown';
  const key = i18n.exists(`errors:${code}.title`) ? code : e && e.status >= 500 ? 'internal_error' : e ? 'generic' : 'unknown';
  const tone = e && (e.status === 403 || e.status === 428) ? 'warn' : 'err';
  const actions: { to?: string; label: string }[] = [];
  if (code.startsWith('k8s_') && code !== 'k8s_not_found' && code !== 'k8s_invalid')
    actions.push({ to: '/settings/kubernetes', label: t('action.checkKubernetes') });
  if (code.startsWith('podman_') && code !== 'podman_not_found') actions.push({ to: '/settings/podman', label: t('action.checkPodman') });
  if (code === 'metrics_unavailable') actions.push({ to: '/settings/kubernetes', label: t('action.configureMetrics') });
  if (code.startsWith('k8s_') || code.startsWith('podman_')) actions.push({ to: '/monitoring/health', label: t('action.health') });

  const params = { ...(e?.params ?? {}), message: e?.message ?? String(error) } as Record<string, unknown>;
  const causes = (e?.params?.causes as { field?: string; message?: string }[] | undefined) ?? [];
  const errors = (e?.params?.errors as { field?: string; message?: string; line?: number }[] | undefined) ?? [];
  return (
    <Alert tone={tone} title={(context ? `${context}: ` : '') + t(`${key}.title`, params)}>
      <p>{t(`${key}.cause`, params)}</p>
      {e?.message && key !== 'unknown' && <p className="small">{e.message}</p>}
      {[...causes, ...errors].length > 0 && (
        <ul className="small">
          {[...causes, ...errors].map((c, i) => (
            <li key={i}>
              {c.field && <code>{c.field}</code>} {c.message}
              {'line' in c && c.line ? ` (${t('line')} ${c.line})` : ''}
            </li>
          ))}
        </ul>
      )}
      <div className="row">
        {onRetry && (
          <button type="button" className="btn sm" onClick={onRetry}>
            <RefreshCw size={14} /> {t('action.retry')}
          </button>
        )}
        {actions.map((a) => (
          <Link key={a.label} className="btn sm" to={a.to!}>
            {a.label}
          </Link>
        ))}
      </div>
      {(e?.details || e?.requestId || !e) && (
        <details className="tech">
          <summary>{t('technical')}</summary>
          <pre>
            {[
              e ? `HTTP ${e.status} · ${e.code}` : String(error),
              e?.details ?? '',
              e?.requestId ? `request id: ${e.requestId}` : '',
            ]
              .filter(Boolean)
              .join('\n')}
          </pre>
        </details>
      )}
    </Alert>
  );
}

export function errorMessage(error: unknown, t: (k: string, o?: Record<string, unknown>) => string): string {
  if (error instanceof ApiError) {
    const key = `errors:${error.code}.title`;
    const translated = t(key, { ...error.params, message: error.message });
    return translated !== key ? `${translated} — ${error.message}` : error.message;
  }
  return String(error);
}
