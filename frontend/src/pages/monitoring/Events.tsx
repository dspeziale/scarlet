import { useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import type { ResourceList, ResourceSummary } from '@/api/types';
import { useApi } from '@/hooks/api';
import { DataTable } from '@/components/DataTable';
import { ErrorPanel } from '@/components/ErrorPanel';
import { HelpLink } from '@/components/HelpLink';
import { NamespaceSelect } from '@/components/NamespaceSelect';
import { Badge, Card, Loading, PageHeader, Segmented } from '@/components/ui';
import { formatAge, formatDate } from '@/utils/format';
import { resourceLink } from '@/utils/links';

type EventRow = ResourceSummary & {
  type?: string;
  reason?: string;
  message?: string;
  object?: { kind?: string; name?: string; namespace?: string };
  count?: number;
  lastTimestamp?: string;
  source?: string;
};

export default function Events() {
  const { t } = useTranslation('monitoring');
  const [params] = useSearchParams();
  const [ns, setNs] = useState(params.get('namespace') ?? '');
  const [type, setType] = useState<'all' | 'Warning' | 'Normal'>((params.get('type') as 'Warning' | null) ?? 'all');
  const [reason, setReason] = useState('');
  const q = useApi<ResourceList>('/k8s/events', { namespace: ns || undefined });
  const all = (q.data?.items ?? []) as EventRow[];
  const reasons = useMemo(() => Array.from(new Set(all.map((e) => e.reason ?? ''))).filter(Boolean).sort(), [all]);
  // Warnings first, then most recent first.
  const rows = useMemo(
    () =>
      all
        .filter((e) => (type === 'all' || e.type === type) && (!reason || e.reason === reason))
        .sort((a, b) => (a.type === b.type ? (b.lastTimestamp ?? '').localeCompare(a.lastTimestamp ?? '') : a.type === 'Warning' ? -1 : 1)),
    [all, type, reason],
  );
  const warnings = all.filter((e) => e.type === 'Warning').length;

  return (
    <>
      <PageHeader title={t('events.title')} subtitle={t('events.subtitle')} help={<HelpLink slug="troubleshooting" />} />
      <Card
        title={t('events.count', { total: all.length, warnings })}
        flush
        actions={
          <div className="row">
            <Segmented
              label={t('events.type')}
              value={type}
              onChange={setType}
              options={[
                { value: 'all', label: t('common:all') },
                { value: 'Warning', label: 'Warning' },
                { value: 'Normal', label: 'Normal' },
              ]}
            />
            <select className="input sm" value={reason} onChange={(e) => setReason(e.target.value)} aria-label={t('events.reason')}>
              <option value="">{t('events.allReasons')}</option>
              {reasons.map((r) => (
                <option key={r}>{r}</option>
              ))}
            </select>
            <NamespaceSelect value={ns} onChange={setNs} />
          </div>
        }
      >
        {q.isLoading && <Loading />}
        {q.error && <div style={{ padding: 12 }}><ErrorPanel error={q.error} onRetry={() => void q.refetch()} /></div>}
        {q.data && (
          <DataTable
            rows={rows}
            rowKey={(e) => `${e.namespace}/${e.name}`}
            emptyText={t('events.none')}
            caption={t('events.title')}
            columns={[
              {
                id: 'type',
                header: t('events.type'),
                value: (e) => e.type ?? '',
                cell: (e) => <Badge tone={e.type === 'Warning' ? 'warn' : 'muted'}>{e.type}</Badge>,
              },
              { id: 'reason', header: t('events.reason'), value: (e) => e.reason ?? '', cell: (e) => <strong>{e.reason}</strong> },
              {
                id: 'object',
                header: t('events.object'),
                value: (e) => `${e.object?.kind}/${e.object?.name}`,
                cell: (e) => {
                  const link = resourceLink(e.object?.kind, e.object?.namespace, e.object?.name);
                  const label = `${e.object?.kind ?? ''}/${e.object?.name ?? ''}`;
                  return link ? <Link to={`${link}?tab=events`}>{label}</Link> : label;
                },
              },
              { id: 'ns', header: t('common:namespace'), value: (e) => e.namespace ?? '', cell: (e) => (e.namespace ? <span className="chip">{e.namespace}</span> : '—') },
              { id: 'message', header: t('events.message'), value: (e) => e.message ?? '', cell: (e) => <span className="small" style={{ display: 'block', maxWidth: 520, overflowWrap: 'anywhere' }}>{e.message}</span> },
              { id: 'count', header: t('events.times'), numeric: true, value: (e) => e.count ?? 1, cell: (e) => e.count ?? 1 },
              { id: 'last', header: t('events.last'), value: (e) => e.lastTimestamp ?? '', cell: (e) => <span title={formatDate(e.lastTimestamp)}>{formatAge(e.lastTimestamp)}</span> },
            ]}
          />
        )}
      </Card>
      <p className="small muted">{t('events.retentionNote')}</p>
    </>
  );
}
