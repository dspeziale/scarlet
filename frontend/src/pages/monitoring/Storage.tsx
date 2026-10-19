import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useApi } from '@/hooks/api';
import { DataTable } from '@/components/DataTable';
import { ErrorPanel } from '@/components/ErrorPanel';
import { HelpLink } from '@/components/HelpLink';
import { Alert, Badge, Card, Loading, PageHeader, Progress, type Tone } from '@/components/ui';
import { formatBytes, formatPercent } from '@/utils/format';
import { resourceLink } from '@/utils/links';

interface StorageData {
  pvcs: { namespace: string; name: string; status: string; capacity: number | null; storageClass: string | null; volume: string | null; usedRatio: number | null }[];
  byClass: { storageClass: string; volumes: number; capacity: number }[];
  storageClasses: number;
  usageSource: string | null;
  prometheusError: string | null;
  partial: { kind: string; code: string; message: string }[];
}

const PHASE_TONE: Record<string, Tone> = { Bound: 'ok', Pending: 'warn', Lost: 'err' };

export default function Storage() {
  const { t } = useTranslation('monitoring');
  const q = useApi<StorageData>('/monitoring/storage');
  return (
    <>
      <PageHeader title={t('storage.title')} subtitle={t('storage.subtitle')} help={<HelpLink slug="persistent-volume-claim" />} />
      {q.isLoading && <Loading />}
      {q.error && <ErrorPanel error={q.error} onRetry={() => void q.refetch()} />}
      {q.data && (
        <>
          {q.data.partial.length > 0 && <Alert tone="warn">{t('partial', { kinds: q.data.partial.map((p) => p.kind).join(', ') })}</Alert>}
          {!q.data.usageSource && (
            <Alert tone="info" title={t('noAdvanced')}>
              <p className="small">{q.data.prometheusError ? t('prometheusError', { error: q.data.prometheusError }) : t('storage.usageNeedsPrometheus')}</p>
            </Alert>
          )}
          <div className="grid cols-3 section">
            {q.data.byClass.length === 0 && (
              <Card>
                <p className="muted">{t('storage.noPv')}</p>
              </Card>
            )}
            {q.data.byClass.map((c) => (
              <Card key={c.storageClass}>
                <div className="stat" style={{ padding: 0 }}>
                  <div className="label">
                    {t('storage.class')}: {c.storageClass === '(none)' ? t('storage.noClass') : <Link to={resourceLink('StorageClass', null, c.storageClass)!}>{c.storageClass}</Link>}
                  </div>
                  <div className="value">{formatBytes(c.capacity)}</div>
                  <div className="sub">{t('storage.volumes', { count: c.volumes })}</div>
                </div>
              </Card>
            ))}
          </div>
          <Card title={t('storage.pvcs')} flush>
            <DataTable
              rows={q.data.pvcs}
              rowKey={(r) => `${r.namespace}/${r.name}`}
              initialSort={{ id: 'status', dir: 'desc' }}
              emptyText={t('storage.noPvc')}
              caption={t('storage.pvcs')}
              columns={[
                { id: 'name', header: 'PVC', value: (r) => r.name, cell: (r) => <Link to={resourceLink('PersistentVolumeClaim', r.namespace, r.name)!}>{r.name}</Link> },
                { id: 'ns', header: t('common:namespace'), value: (r) => r.namespace, cell: (r) => <span className="chip">{r.namespace}</span> },
                { id: 'status', header: t('common:status'), value: (r) => r.status, cell: (r) => <Badge tone={PHASE_TONE[r.status] ?? 'muted'} dot>{r.status}</Badge> },
                { id: 'cap', header: t('storage.capacity'), numeric: true, value: (r) => r.capacity, cell: (r) => formatBytes(r.capacity) },
                {
                  id: 'used',
                  header: t('storage.used'),
                  value: (r) => r.usedRatio,
                  cell: (r) =>
                    r.usedRatio != null ? (
                      <div style={{ minWidth: 140 }}>
                        <div className="small">{formatPercent(r.usedRatio)}</div>
                        <Progress ratio={r.usedRatio} label={`${t('storage.used')} ${r.name}`} />
                      </div>
                    ) : (
                      <span className="muted small">{t('notAvailableShort')}</span>
                    ),
                },
                { id: 'class', header: t('storage.class'), value: (r) => r.storageClass ?? '', cell: (r) => r.storageClass ?? '—' },
                { id: 'vol', header: t('storage.volume'), value: (r) => r.volume ?? '', cell: (r) => (r.volume ? <Link to={resourceLink('PersistentVolume', null, r.volume)!}><code>{r.volume}</code></Link> : '—') },
              ]}
            />
          </Card>
        </>
      )}
    </>
  );
}
