import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { CheckCircle2, AlertTriangle, XCircle, RefreshCw } from 'lucide-react';
import type { HealthCheck } from '@/api/types';
import { useApi } from '@/hooks/api';
import { ErrorPanel } from '@/components/ErrorPanel';
import { Badge, Card, Loading, PageHeader, type Tone } from '@/components/ui';
import { formatBytes, formatDate, formatDuration, formatPercent } from '@/utils/format';

const TONE: Record<HealthCheck['status'], Tone> = { healthy: 'ok', degraded: 'warn', unhealthy: 'err' };
const ICON = {
  healthy: <CheckCircle2 size={20} className="check-ok" aria-hidden="true" />,
  degraded: <AlertTriangle size={20} className="check-warn" aria-hidden="true" />,
  unhealthy: <XCircle size={20} className="check-fail" aria-hidden="true" />,
};
const FIX_LINK: Record<string, string> = {
  kubernetes: '/settings/kubernetes',
  podman: '/settings/podman',
  prometheus: '/settings/kubernetes',
  metrics_server: '/guide/monitoring',
  backup: '/operations/backup',
  configuration: '/settings/system',
  storage: '/guide/backup',
  database: '/guide/proc-restore',
};

function Params({ check }: { check: HealthCheck }) {
  const { t } = useTranslation('monitoring');
  const p = check.params ?? {};
  const items: [string, string][] = [];
  switch (check.id) {
    case 'backend':
      if (p.uptimeSeconds != null) items.push([t('health.uptime'), formatDuration(Number(p.uptimeSeconds))]);
      break;
    case 'database':
      items.push([t('health.schema'), String(p.schemaVersion ?? '—')], [t('health.path'), String(p.path ?? '—')]);
      break;
    case 'kubernetes':
      if (p.version) items.push([t('health.version'), String(p.version)]);
      if (p.context) items.push([t('health.context'), String(p.context)]);
      if (p.code) items.push([t('health.code'), String(p.code)]);
      break;
    case 'podman':
      if (p.version) items.push([t('health.version'), String(p.version)]);
      if (p.rootless != null) items.push([t('health.rootless'), p.rootless ? t('common:yes') : t('common:no')]);
      if (p.code) items.push([t('health.code'), String(p.code)]);
      break;
    case 'storage':
      items.push(
        [t('health.path'), String(p.path ?? '—')],
        [t('health.free'), `${formatBytes(Number(p.freeBytes))} / ${formatBytes(Number(p.totalBytes))} (${formatPercent(Number(p.freeRatio))})`],
      );
      break;
    case 'configuration':
      if (Array.isArray(p.problems) && p.problems.length)
        items.push([t('health.problems'), (p.problems as string[]).map((x) => t(`health.problem.${x}`, { defaultValue: x })).join(' · ')]);
      items.push([t('health.mode'), String(p.mode ?? '—')], [t('health.configFile'), String(p.configFile ?? t('health.noConfigFile'))]);
      break;
    case 'prometheus':
      if (p.targets != null) items.push([t('health.targets'), String(p.targets)]);
      break;
    case 'backup':
      if (p.last) items.push([t('health.lastBackup'), formatDate(String(p.last))]);
      break;
  }
  if (!items.length) return null;
  return (
    <dl className="kv small" style={{ marginTop: 6 }}>
      {items.map(([k, v]) => (
        <div key={k} style={{ display: 'contents' }}>
          <dt>{k}</dt>
          <dd>{v}</dd>
        </div>
      ))}
    </dl>
  );
}

export default function Health() {
  const { t } = useTranslation('monitoring');
  const q = useApi<{ status: HealthCheck['status']; checks: HealthCheck[]; checkedAt: string }>('/health', undefined, { refetchInterval: 30_000 });
  return (
    <>
      <PageHeader
        title={t('health.title')}
        subtitle={t('health.subtitle')}
        actions={
          <button type="button" className="btn" onClick={() => void q.refetch()} disabled={q.isFetching}>
            <RefreshCw size={14} /> {t('health.recheck')}
          </button>
        }
      />
      {q.isLoading && <Loading />}
      {q.error && <ErrorPanel error={q.error} onRetry={() => void q.refetch()} />}
      {q.data && (
        <>
          <div className={`alert tone-${TONE[q.data.status]}`} role="status" aria-live="polite">
            {ICON[q.data.status]}
            <div className="alert-body">
              <div className="alert-title">
                {t('health.overall')}: {t(`common:healthState.${q.data.status}`)}
              </div>
              <p className="small">{t(`health.overallText.${q.data.status}`)}</p>
              <p className="small muted">{t('common:lastUpdate', { time: formatDate(q.data.checkedAt) })}</p>
            </div>
          </div>
          <div className="grid cols-2">
            {q.data.checks.map((c) => (
              <Card key={c.id}>
                <div className="row" style={{ alignItems: 'flex-start', flexWrap: 'nowrap' }}>
                  {ICON[c.status]}
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div className="row between">
                      <h2 style={{ margin: 0, fontSize: 15 }}>{t(`health.check.${c.id}`, { defaultValue: c.id })}</h2>
                      <span className="row">
                        {c.optional && <Badge tone="muted">{t('health.optional')}</Badge>}
                        <Badge tone={TONE[c.status]} dot>
                          {t(`common:healthState.${c.status}`)}
                        </Badge>
                      </span>
                    </div>
                    <p className="small muted" style={{ margin: '2px 0' }}>{t(`health.describe.${c.id}`, { defaultValue: '' })}</p>
                    <p style={{ margin: '4px 0' }}>{t(`health.msg.${c.message}`, { defaultValue: c.message })}</p>
                    <Params check={c} />
                    <div className="row small muted" style={{ marginTop: 6 }}>
                      <span>{t('health.latency', { ms: c.latencyMs })}</span>
                      {c.status !== 'healthy' && FIX_LINK[c.id] && (
                        <Link to={FIX_LINK[c.id]} style={{ marginLeft: 'auto' }}>
                          {t('health.howToFix')}
                        </Link>
                      )}
                    </div>
                  </div>
                </div>
              </Card>
            ))}
          </div>
        </>
      )}
    </>
  );
}
