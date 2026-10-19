import { useMemo } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { RefreshCw } from 'lucide-react';
import { resPath } from '@/api/client';
import type { Issue, ResourceDetail, ResourceSummary } from '@/api/types';
import { useApi } from '@/hooks/api';
import { useAuth } from '@/auth/AuthContext';
import { ErrorPanel } from '@/components/ErrorPanel';
import { HelpLink, KindHelp } from '@/components/HelpLink';
import { IssueCard } from '@/components/IssueCard';
import { LogViewer } from '@/components/LogViewer';
import { useResourceOps, type OpKind } from '@/components/ResourceOps';
import { Alert, Card, Empty, HealthBadge, Loading, PageHeader, SeverityBadge, TabPanel, Tabs } from '@/components/ui';
import { DataTable } from '@/components/DataTable';
import { KIND_GUIDE, REASON_GUIDE } from '@/guide';
import { formatAge } from '@/utils/format';
import { SimpleView } from './detail/SimpleView';
import { RelationsView } from './detail/RelationsView';
import { YamlTab } from './detail/YamlTab';
import { MetricsTab } from './detail/MetricsTab';
import { PodsTab } from './detail/PodsTab';

const HAS_PODS = new Set(['Deployment', 'StatefulSet', 'DaemonSet', 'ReplicaSet', 'Job', 'CronJob', 'Node']);
const HAS_METRICS = new Set(['Pod', 'Deployment', 'StatefulSet', 'DaemonSet', 'Node']);

function EventsTab({ kindKey, namespace, name }: { kindKey: string; namespace: string | null; name: string }) {
  const { t } = useTranslation('k8s');
  const q = useApi<{ items: ResourceSummary[] }>(`${resPath(kindKey, namespace, name)}/events`);
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorPanel error={q.error} onRetry={() => void q.refetch()} />;
  if (!q.data?.items.length) return <Empty>{t('detail.noEvents')}</Empty>;
  return (
    <Card flush>
      <DataTable
        rows={q.data.items as (ResourceSummary & Record<string, any>)[]} // eslint-disable-line @typescript-eslint/no-explicit-any
        rowKey={(r) => r.uid}
        columns={[
          { id: 'type', header: t('col.type'), cell: (r) => <span className={`badge tone-${r.type === 'Warning' ? 'warn' : 'muted'}`}>{r.type}</span>, value: (r) => r.type },
          { id: 'reason', header: t('col.reason'), cell: (r) => <strong>{r.reason}</strong>, value: (r) => r.reason },
          { id: 'msg', header: t('col.message'), cell: (r) => <span className="small">{r.message}</span>, value: (r) => r.message },
          { id: 'count', header: t('col.count'), numeric: true, cell: (r) => r.count, value: (r) => r.count },
          { id: 'src', header: 'Source', cell: (r) => <span className="small muted">{r.source}</span> },
          { id: 'last', header: t('col.lastSeen'), cell: (r) => formatAge(r.lastTimestamp), value: (r) => r.lastTimestamp },
        ]}
      />
    </Card>
  );
}

function DiagnosticsTab({ kindKey, namespace, name }: { kindKey: string; namespace: string | null; name: string }) {
  const { t } = useTranslation('k8s');
  const q = useApi<{ items: Issue[] }>(`${resPath(kindKey, namespace, name)}/diagnose`);
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorPanel error={q.error} onRetry={() => void q.refetch()} />;
  if (!q.data?.items.length) return <Alert tone="ok">{t('detail.noDiagnostics')}</Alert>;
  return (
    <div className="stack" style={{ gap: 12 }}>
      {q.data.items.map((i) => (
        <IssueCard key={i.id} issue={i} />
      ))}
    </div>
  );
}

export default function ResourceDetailPage() {
  const { kind: kindKey = '', namespace: nsParam = '_', name = '' } = useParams();
  const namespace = nsParam === '_' ? null : nsParam;
  const { t } = useTranslation(['k8s', 'nav', 'common']);
  const { can } = useAuth();
  const [params, setParams] = useSearchParams();
  const requestedTab = params.get('tab') ?? 'overview';
  const q = useApi<ResourceDetail>(resPath(kindKey, namespace, name));
  const issues = useApi<{ items: Issue[] }>(`${resPath(kindKey, namespace, name)}/diagnose`, undefined, { enabled: !!q.data });
  const ops = useResourceOps();

  const d = q.data;
  const kind = d?.kind.kind ?? '';
  const s = d?.summary as (ResourceSummary & Record<string, unknown>) | undefined;
  const actions = new Set(d?.kind.actions ?? []);
  const issueCount = issues.data?.items.length ?? 0;
  const worst = issues.data?.items[0];

  const tabs = useMemo(
    () => [
      { id: 'overview', label: t('tabs.overview') },
      { id: 'relations', label: t('tabs.relations'), hidden: ['Namespace', 'Event', 'StorageClass'].includes(kind) },
      { id: 'pods', label: t('tabs.pods'), hidden: !HAS_PODS.has(kind) },
      { id: 'events', label: t('tabs.events') },
      { id: 'logs', label: t('tabs.logs'), hidden: kind !== 'Pod' },
      { id: 'metrics', label: t('tabs.metrics'), hidden: !HAS_METRICS.has(kind) },
      { id: 'yaml', label: t('tabs.yaml') },
      { id: 'diagnostics', label: `${t('tabs.diagnostics')}${issueCount ? ` (${issueCount})` : ''}` },
    ],
    [t, kind, issueCount],
  );

  const tab = tabs.some((x) => x.id === requestedTab && !x.hidden) ? requestedTab : 'overview';

  const setTab = (id: string) => {
    const next = new URLSearchParams(params);
    next.set('tab', id);
    setParams(next, { replace: true });
  };

  if (q.isLoading) return <Loading />;
  if (q.error || !d || !s) {
    return (
      <>
        <PageHeader title={name} breadcrumbs={<Link to={`/k8s/${kindKey}`}>{t(`nav:${kindKey}`, { defaultValue: kindKey })}</Link>} />
        <ErrorPanel error={q.error} onRetry={() => void q.refetch()} />
      </>
    );
  }

  const target = { key: kindKey, kind, name: s.name, namespace: s.namespace, replicas: s.replicas as number | undefined, managed: kind === 'Pod' ? !!s.owner : undefined };
  const btn = (op: OpKind, label: string, perm: string, show = true) =>
    show && can(perm) ? (
      <button key={op} type="button" className={`btn ${op === 'delete' ? 'danger' : ''}`} onClick={() => ops.open(op, target)}>
        {label}
      </button>
    ) : null;

  const containers = ((s.containers as { name: string }[] | undefined) ?? []).map((c) => c.name);

  return (
    <>
      <PageHeader
        breadcrumbs={
          <>
            <Link to={`/k8s/${kindKey}`}>{t(`nav:${kindKey}`, { defaultValue: kind })}</Link>
            {namespace && (
              <>
                {' / '}
                <Link to={`/k8s/${kindKey}?namespace=${encodeURIComponent(namespace)}`}>{namespace}</Link>
              </>
            )}
          </>
        }
        title={
          <>
            <span className="muted" style={{ fontWeight: 400 }}>{kind}</span>
            <span className="mono">{s.name}</span>
            <HealthBadge health={s.health} label={typeof s.status === 'string' ? s.status : undefined} />
            {worst && <SeverityBadge severity={worst.severity} />}
          </>
        }
        help={
          <div className="row" style={{ marginTop: 6 }}>
            <KindHelp kind={kind} slug={KIND_GUIDE[kind]} />
            {worst && REASON_GUIDE[worst.reason] && <HelpLink slug={REASON_GUIDE[worst.reason]} label={t('common:helpHowToFix', { reason: worst.reason })} />}
          </div>
        }
        actions={
          <>
            {btn('scale', t('action.scale'), 'workloads.scale', actions.has('scale'))}
            {btn('restart', t('action.restart'), 'workloads.restart', actions.has('restart'))}
            {kind === 'Deployment' && s.paused ? btn('resume', t('action.resume'), 'workloads.rollout') : btn('pause', t('action.pause'), 'workloads.rollout', actions.has('pause'))}
            {kind === 'Deployment' && (
              <Link className="btn" to={`/operations/rollout?namespace=${encodeURIComponent(s.namespace ?? '')}&name=${encodeURIComponent(s.name)}`}>
                {t('action.rollout')}
              </Link>
            )}
            {kind === 'CronJob' && (s.suspend ? btn('unsuspend', t('action.unsuspend'), 'workloads.rollout') : btn('suspend', t('action.suspend'), 'workloads.rollout'))}
            {btn('trigger', t('action.trigger'), 'workloads.deploy', kind === 'CronJob')}
            {kind === 'Node' && (s.unschedulable ? btn('uncordon', t('action.uncordon'), 'nodes.maintain') : btn('cordon', t('action.cordon'), 'nodes.maintain'))}
            {kind === 'Node' && can('nodes.maintain') && (
              <Link className="btn" to={`/operations/maintenance?node=${encodeURIComponent(s.name)}`}>{t('action.drain')}</Link>
            )}
            {btn('delete', t('action.delete'), kind === 'Pod' ? 'pods.delete' : 'resources.delete', actions.has('delete'))}
            <button type="button" className="btn icon" onClick={() => { void q.refetch(); void issues.refetch(); }} aria-label={t('common:refresh')} title={t('common:refresh')}>
              <RefreshCw size={16} />
            </button>
          </>
        }
      />
      {worst && tab !== 'diagnostics' && (
        <Alert tone={worst.severity === 'CRITICAL' ? 'crit' : worst.severity === 'ERROR' ? 'err' : 'warn'} title={t(`diag:reason.${worst.reason}.title`, { defaultValue: worst.reason })}>
          <p>{t(`diag:reason.${worst.reason}.simple`, { ...worst.facts })}</p>
          <button type="button" className="btn sm" onClick={() => setTab('diagnostics')}>{t('tabs.diagnostics')}</button>
        </Alert>
      )}
      <Tabs tabs={tabs} value={tab} onChange={setTab} label={t('tabs.overview')} />
      <TabPanel id={tab}>
        {tab === 'overview' && <SimpleView data={d} kindKey={kindKey} />}
        {tab === 'relations' && <RelationsView kindKey={kindKey} namespace={namespace} name={name} />}
        {tab === 'pods' && <PodsTab kind={kind} name={s.name} namespace={namespace} />}
        {tab === 'events' && <EventsTab kindKey={kindKey} namespace={namespace} name={name} />}
        {tab === 'logs' &&
          (can('logs.read') ? (
            <LogViewer
              key={`${namespace}/${name}`}
              source={{ path: `${resPath('pods', namespace, name)}/logs`, streamPath: `${resPath('pods', namespace, name)}/logs/stream`, containers, previousSupported: true }}
              initialContainer={params.get('container')}
              initialPrevious={params.get('previous') === '1'}
            />
          ) : (
            <Alert tone="warn">{t('detail.logsPermission')}</Alert>
          ))}
        {tab === 'metrics' && <MetricsTab kindKey={kindKey} namespace={namespace} name={name} />}
        {tab === 'yaml' && <YamlTab key={d.yaml} data={d} onApplied={() => void q.refetch()} />}
        {tab === 'diagnostics' && <DiagnosticsTab kindKey={kindKey} namespace={namespace} name={name} />}
      </TabPanel>
      {ops.dialog}
    </>
  );
}
