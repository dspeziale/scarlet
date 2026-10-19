import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Activity, AlertTriangle, Box, Boxes, Cpu, HardDrive, MemoryStick, RefreshCw, RotateCcw, Server, Siren } from 'lucide-react';
import type { Overview, Severity } from '@/api/types';
import { useApi } from '@/hooks/api';
import { ErrorPanel } from '@/components/ErrorPanel';
import { IssueCard } from '@/components/IssueCard';
import { Alert, Badge, Card, Empty, Loading, PageHeader, Progress, StatCard, type Tone } from '@/components/ui';
import { formatAge, formatBytes, formatCpu, formatDate, formatPercent } from '@/utils/format';
import { resourceLink } from '@/utils/links';

function clusterState(o: Overview): { tone: Tone; key: string } {
  const c = o.issues.counts;
  if (!o.cluster.connected) return { tone: 'err', key: 'unreachable' };
  if (c.CRITICAL > 0) return { tone: 'crit', key: 'critical' };
  if (c.ERROR > 0) return { tone: 'err', key: 'errors' };
  if (c.WARNING > 0) return { tone: 'warn', key: 'warnings' };
  return { tone: 'ok', key: 'healthy' };
}

function UsageBar({ label, icon, used, total, requested, metrics }: { label: string; icon: React.ReactNode; used: number | null; total: number; requested: number; metrics: boolean; }) {
  const { t } = useTranslation('dashboard');
  const isCpu = label === 'CPU';
  const fmt = (v: number) => (isCpu ? `${formatCpu(v)} ${t('common:cores')}` : formatBytes(v));
  return (
    <div className="bar-item">
      <div className="row between">
        <span className="row">{icon}<strong>{label}</strong></span>
        <span className="small muted">{t('allocatable')}: {fmt(total)}</span>
      </div>
      {metrics && used !== null ? (
        <>
          <Progress ratio={total ? used / total : null} label={`${label} ${t('usage')}`} />
          <div className="small">{t('usage')}: <strong>{fmt(used)}</strong> ({formatPercent(total ? used / total : null)})</div>
        </>
      ) : (
        <div className="small muted">{t('usageUnavailable')}</div>
      )}
      <div style={{ marginTop: 6 }}>
        <Progress ratio={total ? requested / total : null} tone="info" label={`${label} ${t('requested')}`} />
        <div className="small">{t('requested')}: {fmt(requested)} ({formatPercent(total ? requested / total : null)})</div>
      </div>
    </div>
  );
}

export default function Dashboard() {
  const { t } = useTranslation('dashboard');
  const q = useApi<Overview>('/cluster/overview', undefined, { refetchInterval: 30_000 });

  if (q.isLoading) return <Loading />;
  if (q.error || !q.data) {
    return (
      <>
        <PageHeader title={t('title')} />
        <ErrorPanel error={q.error} onRetry={() => void q.refetch()} context={t('loadError')} />
      </>
    );
  }
  const o = q.data;
  const state = clusterState(o);
  const counts = o.issues.counts;
  const r = o.resources;

  return (
    <>
      <PageHeader
        title={t('title')}
        subtitle={t('subtitle')}
        actions={
          <>
            <span className="small muted">{t('common:lastUpdate', { time: formatDate(q.dataUpdatedAt) })}</span>
            <button type="button" className="btn" onClick={() => void q.refetch()} disabled={q.isFetching}>
              <RefreshCw size={16} /> {t('common:refresh')}
            </button>
          </>
        }
      />
      {o.partial.length > 0 && <Alert tone="warn">{t('diag:partialData', { kinds: o.partial.map((p) => p.kind).join(', ') })}</Alert>}

      <section className="section grid cols-4" aria-label={t('summary')}>
        <StatCard to="/operations-center" tone={state.tone} icon={<Activity size={15} />} label={t('clusterState')} value={t(`state.${state.key}`)}
          sub={t('diag:counts', { critical: counts.CRITICAL, error: counts.ERROR, warning: counts.WARNING })} />
        <StatCard to="/k8s/nodes" tone={o.nodes.notReady ? 'err' : 'ok'} icon={<Server size={15} />} label={t('nodes')} value={`${o.nodes.ready}/${o.nodes.total}`}
          sub={o.nodes.notReady ? t('nodesNotReady', { count: o.nodes.notReady }) : o.nodes.cordoned ? t('nodesCordoned', { count: o.nodes.cordoned }) : t('allReady')} />
        <StatCard to="/k8s/pods" icon={<Box size={15} />} label={t('podsRunning')} value={o.pods.running}
          sub={t('podsTotal', { total: o.pods.total, pending: o.pods.pending, completed: o.pods.completed })} />
        <StatCard to="/k8s/pods?health=failed" tone={o.pods.failed ? 'err' : 'ok'} icon={<AlertTriangle size={15} />} label={t('podsFailed')} value={o.pods.failed}
          sub={o.pods.failed ? t('podsFailedHint') : t('none')} />
        <StatCard to="/k8s/deployments" icon={<Boxes size={15} />} label={t('deployments')} value={o.deployments.total}
          sub={t('deploymentsHealthy', { count: o.deployments.healthy })} />
        <StatCard to="/k8s/deployments?health=problems" tone={o.deployments.failed ? 'err' : o.deployments.degraded ? 'warn' : 'ok'} icon={<Boxes size={15} />}
          label={t('deploymentsDegraded')} value={o.deployments.degraded + o.deployments.failed}
          sub={t('degradedDetail', { failed: o.deployments.failed, degraded: o.deployments.degraded })} />
        <StatCard to="/k8s/events" tone={o.events.warnings ? 'warn' : 'ok'} icon={<Siren size={15} />} label={t('warnings')} value={o.events.warnings} sub={t('warningsHint')} />
        <StatCard to="/k8s/pods" tone={o.restarts.total > 20 ? 'warn' : undefined} icon={<RotateCcw size={15} />} label={t('restarts')} value={o.restarts.total} sub={t('restartsHint')} />
      </section>

      <div className="grid cols-3 section">
        <Card title={t('resources')} actions={<Link to="/monitoring/cpu" className="small">{t('common:details')}</Link>}>
          {!r.metricsAvailable && <p className="small muted">{t('metricsMissing')}</p>}
          <div className="bar-list">
            <UsageBar label="CPU" icon={<Cpu size={15} />} used={r.usage?.cpu ?? null} total={r.allocatableCpu} requested={r.requestedCpu} metrics={r.metricsAvailable} />
            <UsageBar label={t('memory')} icon={<MemoryStick size={15} />} used={r.usage?.memory ?? null} total={r.allocatableMemory} requested={r.requestedMemory} metrics={r.metricsAvailable} />
          </div>
        </Card>
        <Card title={t('storage')} actions={<Link to="/monitoring/storage" className="small">{t('common:details')}</Link>}>
          <div className="stack">
            <div className="row"><HardDrive size={15} /> <strong>{o.storage.pvCount}</strong> {t('pvs')} · {formatBytes(o.storage.pvCapacity)}</div>
            <div>
              <Link to="/k8s/persistentvolumeclaims">{t('pvcs')}</Link>: {o.storage.pvcBound} {t('bound')}
              {o.storage.pvcPending > 0 && <> · <Badge tone="warn">{o.storage.pvcPending} pending</Badge></>}
            </div>
            <div className="small muted">{t('storageHint')}</div>
          </div>
        </Card>
        <Card title={t('topRestarts')}>
          {o.restarts.top.length === 0 ? (
            <Empty>{t('noRestarts')}</Empty>
          ) : (
            <ul className="stack" style={{ listStyle: 'none', margin: 0, padding: 0 }}>
              {o.restarts.top.map((p) => (
                <li key={`${p.namespace}/${p.name}`} className="row between">
                  <Link to={resourceLink('Pod', p.namespace, p.name)!} className="mono small ellipsis" style={{ maxWidth: '70%' }}>{p.name}</Link>
                  <Badge tone={p.restarts > 5 ? 'warn' : 'muted'}>{p.restarts}</Badge>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <div className="grid cols-2 section">
        <Card title={t('recentProblems')} actions={<Link to="/operations-center" className="small">{t('common:viewAll')}</Link>}>
          {o.issues.top.length === 0 ? (
            <Alert tone="ok">{t('diag:noIssues')}</Alert>
          ) : (
            <div className="stack" style={{ gap: 10 }}>
              {o.issues.top.slice(0, 5).map((i) => <IssueCard key={i.id} issue={i} compact />)}
            </div>
          )}
        </Card>
        <Card title={t('criticalEvents')} actions={<Link to="/monitoring/events" className="small">{t('common:viewAll')}</Link>} flush>
          {o.events.recent.length === 0 ? (
            <Empty>{t('noWarnings')}</Empty>
          ) : (
            <table className="data">
              <thead>
                <tr>
                  <th scope="col">{t('k8s:col.reason')}</th>
                  <th scope="col">{t('k8s:col.object')}</th>
                  <th scope="col">{t('k8s:col.message')}</th>
                  <th scope="col">{t('k8s:col.lastSeen')}</th>
                </tr>
              </thead>
              <tbody>
                {o.events.recent.map((e) => {
                  const obj = e.object as { kind: string; name: string; namespace: string };
                  const link = resourceLink(obj.kind, obj.namespace, obj.name);
                  return (
                    <tr key={e.uid}>
                      <td><Badge tone="warn">{String(e.reason)}</Badge></td>
                      <td className="small">{link ? <Link to={link}>{obj.kind}/{obj.name}</Link> : `${obj.kind}/${obj.name}`}</td>
                      <td className="small">{String(e.message ?? '')}</td>
                      <td className="small nowrap">{formatAge(e.lastTimestamp as string)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </Card>
      </div>
      <SeverityLegend />
    </>
  );
}

function SeverityLegend() {
  const { t } = useTranslation();
  return (
    <p className="small muted">
      {(['CRITICAL', 'ERROR', 'WARNING', 'INFO'] as Severity[]).map((s) => (
        <span key={s} style={{ marginRight: 14 }}>
          <strong>{s}</strong>: {t(`severityHelp.${s}`)}
        </span>
      ))}
    </p>
  );
}
