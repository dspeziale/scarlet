import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useApi } from '@/hooks/api';
import { DataTable } from '@/components/DataTable';
import { ErrorPanel } from '@/components/ErrorPanel';
import { HelpLink } from '@/components/HelpLink';
import { NamespaceSelect } from '@/components/NamespaceSelect';
import { Alert, Badge, Card, Loading, PageHeader, Progress } from '@/components/ui';
import { formatBytes, formatCpu, formatPercent } from '@/utils/format';
import { resourceLink } from '@/utils/links';
import { PromHistory, type Sources } from './charts';

interface NodeRow {
  name: string;
  ready: boolean;
  unschedulable: boolean;
  allocatableCpu: number | null;
  allocatableMemory: number | null;
  allocatablePods: number;
  usageCpu: number | null;
  usageMemory: number | null;
  requests: { cpu: number; memory: number; cpuLimit: number; memoryLimit: number; pods: number };
  pressures: string[];
}

interface PodRow {
  namespace: string;
  name: string;
  cpu: number;
  memory: number;
  cpuRequest: number | null;
  memoryRequest: number | null;
  cpuLimit: number | null;
  memoryLimit: number | null;
  memoryLimitRatio: number | null;
  node: string | null;
}

const ratio = (a: number | null | undefined, b: number | null | undefined) => (a != null && b ? a / b : null);

/** CPU or memory monitoring page: usage (metrics-server) vs allocatable and requests (always available). */
export function UsagePage({ resource }: { resource: 'cpu' | 'memory' }) {
  const { t } = useTranslation('monitoring');
  const [ns, setNs] = useState('');
  const isCpu = resource === 'cpu';
  const fmt = (v: number | null | undefined) => (isCpu ? formatCpu(v) : formatBytes(v));
  const sources = useApi<Sources>('/monitoring/sources', undefined, { staleTime: 60_000 });
  const nodes = useApi<{ metricsServer: boolean; nodes: NodeRow[] }>('/monitoring/nodes');
  const pods = useApi<{ metricsServer: boolean; pods: PodRow[]; total?: number }>('/monitoring/pods', { namespace: ns || undefined, sort: resource, limit: 50 });
  const ms = nodes.data?.metricsServer ?? true;

  const totals = (nodes.data?.nodes ?? []).filter((n) => n.ready).reduce(
    (acc, n) => {
      acc.alloc += (isCpu ? n.allocatableCpu : n.allocatableMemory) ?? 0;
      acc.req += isCpu ? n.requests.cpu : n.requests.memory;
      acc.lim += isCpu ? n.requests.cpuLimit : n.requests.memoryLimit;
      acc.use += (isCpu ? n.usageCpu : n.usageMemory) ?? 0;
      return acc;
    },
    { alloc: 0, req: 0, lim: 0, use: 0 },
  );

  return (
    <>
      <PageHeader
        title={t(`${resource}.title`)}
        subtitle={t(`${resource}.subtitle`)}
        help={<HelpLink slug={isCpu ? 'resource-request' : 'resource-limit'} />}
      />
      {nodes.isLoading && <Loading />}
      {nodes.error && <ErrorPanel error={nodes.error} onRetry={() => void nodes.refetch()} />}
      {nodes.data && !ms && (
        <Alert tone="warn" title={t('noAdvanced')}>
          <p>{t('noMetricsServer')}</p>
        </Alert>
      )}
      {nodes.data && (
        <>
          <div className="grid cols-4 section">
            <Card>
              <div className="stat" style={{ padding: 0 }}>
                <div className="label">{t('allocatable')}</div>
                <div className="value">{fmt(totals.alloc)}</div>
                <div className="sub">{t('readyNodesOnly')}</div>
              </div>
            </Card>
            <Card>
              <div className="stat" style={{ padding: 0 }}>
                <div className="label">{t('usage')}</div>
                <div className="value">{ms ? fmt(totals.use) : '—'}</div>
                <div className="sub">{ms ? formatPercent(ratio(totals.use, totals.alloc)) + ' ' + t('ofAllocatable') : t('notMeasured')}</div>
              </div>
            </Card>
            <Card>
              <div className="stat" style={{ padding: 0 }}>
                <div className="label">{t('requested')}</div>
                <div className="value">{fmt(totals.req)}</div>
                <div className="sub">{formatPercent(ratio(totals.req, totals.alloc))} {t('ofAllocatable')}</div>
              </div>
            </Card>
            <Card>
              <div className="stat" style={{ padding: 0 }}>
                <div className="label">{t('limits')}</div>
                <div className="value">{fmt(totals.lim)}</div>
                <div className="sub">{formatPercent(ratio(totals.lim, totals.alloc))} {t('ofAllocatable')} · {t('overcommitHint')}</div>
              </div>
            </Card>
          </div>
          <Alert tone="info">
            <p className="small">{t('requestsExplain')}</p>
          </Alert>
          <div className="section">
            <Card title={t('perNode')} flush>
              <div className="table-wrap">
                <table className="data">
                  <caption className="sr-only">{t('perNode')}</caption>
                  <thead>
                    <tr>
                      <th scope="col">{t('node')}</th>
                      <th scope="col">{t('usage')}</th>
                      <th scope="col">{t('requested')}</th>
                      <th scope="col" className="num">{t('allocatable')}</th>
                      <th scope="col" className="num">Pod</th>
                    </tr>
                  </thead>
                  <tbody>
                    {nodes.data.nodes.map((n) => {
                      const alloc = isCpu ? n.allocatableCpu : n.allocatableMemory;
                      const use = isCpu ? n.usageCpu : n.usageMemory;
                      const req = isCpu ? n.requests.cpu : n.requests.memory;
                      return (
                        <tr key={n.name}>
                          <td>
                            <Link to={resourceLink('Node', null, n.name)!}>{n.name}</Link>{' '}
                            {!n.ready && <Badge tone="err">NotReady</Badge>} {n.unschedulable && <Badge tone="muted">cordon</Badge>}
                            {n.pressures.map((p) => (
                              <Badge key={p} tone="warn">{p}</Badge>
                            ))}
                          </td>
                          <td style={{ minWidth: 180 }}>
                            {use != null ? (
                              <>
                                <div className="small">{fmt(use)} · {formatPercent(ratio(use, alloc))}</div>
                                <Progress ratio={ratio(use, alloc)} label={`${t('usage')} ${n.name}`} />
                              </>
                            ) : (
                              <span className="muted small">{t('notMeasured')}</span>
                            )}
                          </td>
                          <td style={{ minWidth: 180 }}>
                            <div className="small">{fmt(req)} · {formatPercent(ratio(req, alloc))}</div>
                            <Progress ratio={ratio(req, alloc)} label={`${t('requested')} ${n.name}`} tone="info" />
                          </td>
                          <td className="num">{fmt(alloc)}</td>
                          <td className="num">
                            {n.requests.pods}/{n.allocatablePods}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </Card>
          </div>
        </>
      )}
      <div className="grid cols-2 section">
        <PromHistory query={isCpu ? 'cluster_cpu' : 'cluster_memory'} title={t(`${resource}.history`)} format={(v) => fmt(v)} sources={sources.data} />
        {isCpu && <PromHistory query="cluster_network_rx" title={t('networkRx')} format={(v) => `${formatBytes(v)}/s`} sources={sources.data} />}
        {isCpu && <PromHistory query="cluster_network_tx" title={t('networkTx')} format={(v) => `${formatBytes(v)}/s`} sources={sources.data} />}
      </div>
      {sources.data && !sources.data.prometheus.ok && (
        <p className="small muted">
          {sources.data.prometheus.configured ? t('prometheusError', { error: sources.data.prometheus.error ?? '' }) : t('prometheusNotConfigured')}{' '}
          <Link to="/settings/kubernetes">{t('configure')}</Link>
        </p>
      )}
      <Card
        title={t('topPods')}
        flush
        actions={<NamespaceSelect value={ns} onChange={setNs} />}
      >
        {pods.isLoading && <Loading />}
        {pods.error && <div style={{ padding: 12 }}><ErrorPanel error={pods.error} onRetry={() => void pods.refetch()} /></div>}
        {pods.data && !pods.data.metricsServer && <p className="muted" style={{ padding: 12 }}>{t('noMetricsServerShort')}</p>}
        {pods.data?.metricsServer && (
          <DataTable
            rows={pods.data.pods}
            rowKey={(r) => `${r.namespace}/${r.name}`}
            initialSort={{ id: 'value', dir: 'desc' }}
            columns={[
              { id: 'name', header: 'Pod', value: (r) => r.name, cell: (r) => <Link to={`${resourceLink('Pod', r.namespace, r.name)}?tab=metrics`}>{r.name}</Link> },
              { id: 'ns', header: t('common:namespace'), value: (r) => r.namespace, cell: (r) => <span className="chip">{r.namespace}</span> },
              { id: 'value', header: t('usage'), numeric: true, value: (r) => (isCpu ? r.cpu : r.memory), cell: (r) => fmt(isCpu ? r.cpu : r.memory) },
              { id: 'req', header: t('request'), numeric: true, value: (r) => (isCpu ? r.cpuRequest : r.memoryRequest), cell: (r) => fmt(isCpu ? r.cpuRequest : r.memoryRequest) },
              { id: 'lim', header: t('limit'), numeric: true, value: (r) => (isCpu ? r.cpuLimit : r.memoryLimit), cell: (r) => ((isCpu ? r.cpuLimit : r.memoryLimit) ? fmt(isCpu ? r.cpuLimit : r.memoryLimit) : <span className="muted">{t('noLimit')}</span>) },
              ...(isCpu
                ? []
                : [
                    {
                      id: 'ratio',
                      header: t('ofLimit'),
                      numeric: true,
                      value: (r: PodRow) => r.memoryLimitRatio,
                      cell: (r: PodRow) =>
                        r.memoryLimitRatio != null ? (
                          <span className={r.memoryLimitRatio > 0.9 ? 'check-fail' : r.memoryLimitRatio > 0.8 ? 'check-warn' : undefined} title={r.memoryLimitRatio > 0.8 ? t('nearLimit') : undefined}>
                            {formatPercent(r.memoryLimitRatio)}
                          </span>
                        ) : (
                          '—'
                        ),
                    },
                  ]),
              { id: 'node', header: t('node'), value: (r) => r.node ?? '', cell: (r) => r.node ?? '—' },
            ]}
            caption={t('topPods')}
          />
        )}
        {pods.data?.metricsServer && pods.data.total != null && pods.data.total > pods.data.pods.length && (
          <p className="small muted" style={{ padding: '0 12px 12px' }}>{t('topOf', { shown: pods.data.pods.length, total: pods.data.total })}</p>
        )}
      </Card>
    </>
  );
}
