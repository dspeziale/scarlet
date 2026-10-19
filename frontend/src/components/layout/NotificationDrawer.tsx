import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Check, RefreshCw, Undo2, X } from 'lucide-react';
import { post } from '@/api/client';
import type { Notification, NotificationCounts, Severity } from '@/api/types';
import { useAction, useApi } from '@/hooks/api';
import { useAuth } from '@/auth/AuthContext';
import { ErrorPanel } from '../ErrorPanel';
import { Empty, Loading, Segmented, SeverityBadge } from '../ui';
import { formatAge } from '@/utils/format';
import { resourceLink } from '@/utils/links';

export function NotificationDrawer({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation();
  const { can } = useAuth();
  const [status, setStatus] = useState<'active' | 'open' | 'acknowledged' | 'resolved'>('active');
  const [severity, setSeverity] = useState<'' | Severity>('');
  const [q, setQ] = useState('');
  const ref = useRef<HTMLDivElement>(null);
  const list = useApi<{ items: Notification[]; total: number; counts: NotificationCounts }>('/notifications', {
    status,
    severity: severity || undefined,
    q: q || undefined,
    limit: 100,
  });
  const ack = useAction((n: Notification) => post(`/notifications/${n.id}/${n.status === 'acknowledged' ? 'unack' : 'ack'}`));
  const refresh = useAction(() => post('/notifications/refresh'));

  useEffect(() => {
    ref.current?.querySelector<HTMLElement>('input')?.focus();
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  return createPortal(
    <>
      <div className="overlay" style={{ background: 'rgba(8,14,22,.3)' }} onMouseDown={onClose} />
      <div className="drawer" role="dialog" aria-modal="true" aria-labelledby="notif-title" ref={ref}>
        <div className="drawer-header">
          <h2 id="notif-title">{t('notifications.title')}</h2>
          <button type="button" className="btn sm" onClick={() => void refresh.run()} disabled={refresh.busy} title={t('notifications.refresh')}>
            <RefreshCw size={14} /> {t('notifications.refresh')}
          </button>
          <button type="button" className="btn ghost icon" onClick={onClose} aria-label={t('close')}>
            <X size={18} />
          </button>
        </div>
        <div style={{ padding: '10px 16px', borderBottom: '1px solid var(--border)' }} className="stack">
          <Segmented
            label={t('notifications.status')}
            value={status}
            onChange={setStatus}
            options={(['active', 'open', 'acknowledged', 'resolved'] as const).map((s) => ({ value: s, label: t(`notifications.st.${s}`) }))}
          />
          <div className="row">
            <select className="input sm" value={severity} onChange={(e) => setSeverity(e.target.value as Severity | '')} aria-label={t('severity')}>
              <option value="">{t('allSeverities')}</option>
              {(['CRITICAL', 'ERROR', 'WARNING', 'INFO'] as Severity[]).map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
            <input className="input sm" style={{ flex: 1 }} placeholder={t('search')} aria-label={t('search')} value={q} onChange={(e) => setQ(e.target.value)} />
          </div>
        </div>
        <div className="drawer-body">
          {list.isLoading && <Loading />}
          {list.error && <div style={{ padding: 12 }}><ErrorPanel error={list.error} onRetry={() => void list.refetch()} /></div>}
          {list.data && list.data.items.length === 0 && <Empty>{t('notifications.none')}</Empty>}
          <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
            {list.data?.items.map((n) => {
              const link = n.source === 'system' ? (n.resource_name === 'podman' ? '/settings/podman' : '/settings/kubernetes') : resourceLink(n.resource_kind, n.namespace, n.resource_name);
              return (
                <li key={n.id} style={{ padding: '10px 16px', borderBottom: '1px solid var(--border)' }}>
                  <div className="row between">
                    <div className="row">
                      <SeverityBadge severity={n.severity} />
                      <strong>{t(`diag:reason.${n.reason}.title`, { defaultValue: n.reason })}</strong>
                    </div>
                    <span className="small muted" title={n.last_seen}>
                      {formatAge(n.last_seen)}
                    </span>
                  </div>
                  <div className="small" style={{ marginTop: 4 }}>
                    {link ? (
                      <Link to={link} onClick={onClose}>
                        {n.resource_kind} {n.namespace ? `${n.namespace}/` : ''}
                        {n.resource_name}
                      </Link>
                    ) : (
                      <span>
                        {n.resource_kind} {n.resource_name}
                      </span>
                    )}
                  </div>
                  {n.message && <div className="small muted ellipsis" title={n.message}>{n.message}</div>}
                  <div className="row small" style={{ marginTop: 6 }}>
                    <span className={`badge tone-${n.status === 'resolved' ? 'ok' : n.status === 'acknowledged' ? 'info' : 'warn'}`}>{t(`notifications.st.${n.status}`)}</span>
                    {n.status === 'acknowledged' && <span className="muted">{t('notifications.ackBy', { user: n.acknowledged_by })}</span>}
                    {n.status !== 'resolved' && can('notifications.ack') && (
                      <button type="button" className="btn sm" style={{ marginLeft: 'auto' }} onClick={() => void ack.run(n)} disabled={ack.busy}>
                        {n.status === 'acknowledged' ? <Undo2 size={14} /> : <Check size={14} />}
                        {n.status === 'acknowledged' ? t('notifications.unack') : t('notifications.ack')}
                      </button>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>
        </div>
        <div style={{ padding: 10, borderTop: '1px solid var(--border)' }}>
          <Link to="/operations-center" className="btn primary" style={{ width: '100%' }} onClick={onClose}>
            {t('notifications.openCenter')}
          </Link>
        </div>
      </div>
    </>,
    document.body,
  );
}
