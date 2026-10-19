import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { RefreshCw } from 'lucide-react';
import type { Issue, Severity } from '@/api/types';
import { post } from '@/api/client';
import { useAction, useApi, useLocalState } from '@/hooks/api';
import { ErrorPanel } from '@/components/ErrorPanel';
import { IssueCard } from '@/components/IssueCard';
import { NamespaceSelect } from '@/components/NamespaceSelect';
import { HelpLink } from '@/components/HelpLink';
import { Alert, Loading, PageHeader, SEVERITY_TONE } from '@/components/ui';

export default function OperationsCenter() {
  const { t } = useTranslation(['diag', 'common']);
  const [namespace, setNamespace] = useState('');
  const [severity, setSeverity] = useState<'' | Severity>('');
  const [q, setQ] = useState('');
  const [hideAck, setHideAck] = useLocalState('pkm.center.hideAck', false);
  const issues = useApi<{ items: Issue[]; counts: Record<Severity, number>; partial: { kind: string }[] }>('/cluster/issues', {
    namespace: namespace || undefined,
  });
  const recheck = useAction(() => post('/notifications/refresh'), { success: t('common:notifications.refresh') });

  const items = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return (issues.data?.items ?? []).filter(
      (i) =>
        (!severity || i.severity === severity) &&
        (!hideAck || !i.acknowledged) &&
        (!needle || `${i.name} ${i.namespace} ${i.reason} ${i.owner?.name ?? ''} ${i.node ?? ''}`.toLowerCase().includes(needle)),
    );
  }, [issues.data, severity, hideAck, q]);

  const counts = issues.data?.counts;
  return (
    <>
      <PageHeader
        title={t('centerTitle')}
        subtitle={t('centerSubtitle')}
        help={<HelpLink slug="proc-gestione-incidenti" />}
        actions={
          <button type="button" className="btn" onClick={() => void recheck.run().then(() => issues.refetch())} disabled={recheck.busy || issues.isFetching}>
            <RefreshCw size={16} /> {t('common:notifications.refresh')}
          </button>
        }
      />
      {counts && (
        <div className="row section" role="group" aria-label={t('common:severity')}>
          {(['CRITICAL', 'ERROR', 'WARNING', 'INFO'] as Severity[]).map((s) => (
            <button
              key={s}
              type="button"
              className={`btn ${severity === s ? 'primary' : ''}`}
              aria-pressed={severity === s}
              onClick={() => setSeverity(severity === s ? '' : s)}
              title={t(`common:severityHelp.${s}`)}
            >
              <span className={`badge sev tone-${SEVERITY_TONE[s]}`}>{s}</span> {counts[s]}
            </button>
          ))}
        </div>
      )}
      <div className="row section">
        <NamespaceSelect value={namespace} onChange={setNamespace} />
        <input className="input sm" style={{ minWidth: 240 }} placeholder={t('common:filter')} aria-label={t('common:filter')} value={q} onChange={(e) => setQ(e.target.value)} />
        <label className="checkbox small">
          <input type="checkbox" checked={hideAck} onChange={(e) => setHideAck(e.target.checked)} />
          {t('onlyActive')}
        </label>
      </div>
      {issues.isLoading && <Loading />}
      {issues.error && <ErrorPanel error={issues.error} onRetry={() => void issues.refetch()} />}
      {issues.data && issues.data.partial.length > 0 && (
        <Alert tone="warn">{t('partialData', { kinds: issues.data.partial.map((p) => p.kind).join(', ') })}</Alert>
      )}
      {issues.data && items.length === 0 && <Alert tone="ok">{t('noIssues')}</Alert>}
      <div className="stack" style={{ gap: 12 }} aria-live="polite">
        {items.map((i) => (
          <IssueCard key={i.id} issue={i} />
        ))}
      </div>
    </>
  );
}
