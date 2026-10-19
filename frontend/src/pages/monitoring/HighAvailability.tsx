import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import type { Health } from '@/api/types';
import { useApi } from '@/hooks/api';
import { DataTable } from '@/components/DataTable';
import { ErrorPanel } from '@/components/ErrorPanel';
import { HelpLink } from '@/components/HelpLink';
import { NamespaceSelect } from '@/components/NamespaceSelect';
import { Alert, Badge, Card, HealthBadge, Loading, PageHeader, StatCard, type Tone } from '@/components/ui';
import { resourceLink } from '@/utils/links';

interface HaWorkload {
  kind: string;
  name: string;
  namespace: string;
  replicas: number;
  ready: number;
  health: Health;
  nodes: string[];
  pdb: string | null;
  strategy: string | null;
  restarts: number;
  flags: string[];
}
interface HaData {
  workloads: HaWorkload[];
  nodes: { name: string; health: Health; ready: boolean; pressures: string[]; unschedulable: boolean; roles: string[] }[];
  readyNodes: number;
  partial: { kind: string; code: string; message: string }[];
}

const FLAG_TONE: Record<string, Tone> = {
  single_replica: 'warn',
  same_node: 'warn',
  no_pdb: 'info',
  no_readiness: 'warn',
  no_liveness: 'info',
  no_requests: 'info',
  no_memory_limit: 'info',
};

const CONCEPTS: [string, string][] = [
  ['replica', 'replica'],
  ['rollingUpdate', 'rolling-update'],
  ['rollback', 'rollback'],
  ['readiness', 'readiness-probe'],
  ['liveness', 'liveness-probe'],
  ['request', 'resource-request'],
  ['limit', 'resource-limit'],
  ['disruption', 'alta-disponibilita'],
];

export default function HighAvailability() {
  const { t } = useTranslation('monitoring');
  const [ns, setNs] = useState('');
  const q = useApi<HaData>('/cluster/ha', { namespace: ns || undefined });
  const ws = q.data?.workloads ?? [];
  const resilient = ws.filter((w) => w.replicas > 1 && w.nodes.length > 1 && w.ready >= w.replicas).length;
  const single = ws.filter((w) => w.flags.includes('single_replica') && w.replicas > 0).length;

  const sentence = (w: HaWorkload) => {
    if (w.replicas === 0) return t('ha.sentence.stopped');
    if (w.replicas === 1) return t('ha.sentence.single');
    if (w.nodes.length <= 1) return t('ha.sentence.sameNode', { count: w.replicas });
    return t('ha.sentence.multi', { count: w.replicas, nodes: w.nodes.length });
  };

  return (
    <>
      <PageHeader title={t('ha.title')} subtitle={t('ha.subtitle')} help={<HelpLink slug="alta-disponibilita" />} actions={<NamespaceSelect value={ns} onChange={setNs} />} />
      <details className="card section" style={{ padding: '10px 16px' }}>
        <summary style={{ cursor: 'pointer', fontWeight: 600 }}>{t('ha.conceptsTitle')}</summary>
        <div className="grid cols-2" style={{ marginTop: 10 }}>
          {CONCEPTS.map(([k, slug]) => (
            <div key={k}>
              <h3 style={{ marginBottom: 2 }}>{t(`ha.concept.${k}.title`)}</h3>
              <p className="small" style={{ marginBottom: 2 }}>{t(`ha.concept.${k}.text`)}</p>
              <HelpLink slug={slug} label={t('ha.readMore')} />
            </div>
          ))}
        </div>
      </details>
      {q.isLoading && <Loading />}
      {q.error && <ErrorPanel error={q.error} onRetry={() => void q.refetch()} />}
      {q.data && (
        <>
          {q.data.partial.length > 0 && <Alert tone="warn">{t('partial', { kinds: q.data.partial.map((p) => p.kind).join(', ') })}</Alert>}
          <div className="grid cols-4 section">
            <StatCard label={t('ha.readyNodes')} value={`${q.data.readyNodes}/${q.data.nodes.length}`} tone={q.data.readyNodes < q.data.nodes.length ? 'err' : 'ok'} to="/k8s/nodes" />
            <StatCard label={t('ha.workloads')} value={ws.length} />
            <StatCard label={t('ha.resilient')} value={resilient} sub={t('ha.resilientHint')} tone="ok" />
            <StatCard label={t('ha.singleReplica')} value={single} sub={t('ha.singleHint')} tone={single ? 'warn' : undefined} />
          </div>
          {q.data.readyNodes < 2 && q.data.nodes.length > 0 && <Alert tone="warn">{t('ha.fewNodes')}</Alert>}
          <Card title={t('ha.workloads')} flush>
            <DataTable
              rows={ws}
              rowKey={(w) => `${w.kind}/${w.namespace}/${w.name}`}
              initialSort={{ id: 'flags', dir: 'desc' }}
              caption={t('ha.workloads')}
              columns={[
                {
                  id: 'name',
                  header: t('ha.application'),
                  value: (w) => w.name,
                  cell: (w) => (
                    <div>
                      <Link to={resourceLink(w.kind, w.namespace, w.name)!}>
                        <strong>{w.name}</strong>
                      </Link>{' '}
                      <span className="small muted">{w.kind}</span>
                      <div className="small muted" style={{ maxWidth: 380 }}>{sentence(w)}</div>
                    </div>
                  ),
                },
                { id: 'ns', header: t('common:namespace'), value: (w) => w.namespace, cell: (w) => <span className="chip">{w.namespace}</span> },
                { id: 'ready', header: t('ha.replicas'), value: (w) => w.ready, cell: (w) => <span className="nowrap"><HealthBadge health={w.health} label={`${w.ready}/${w.replicas}`} /></span> },
                { id: 'nodes', header: t('ha.nodes'), value: (w) => w.nodes.length, cell: (w) => (w.nodes.length ? w.nodes.map((n) => <span key={n} className="chip">{n}</span>) : '—') },
                { id: 'pdb', header: 'PDB', value: (w) => w.pdb ?? '', cell: (w) => (w.pdb ? <code>{w.pdb}</code> : <span className="muted">—</span>) },
                { id: 'strategy', header: t('ha.strategy'), value: (w) => w.strategy ?? '', cell: (w) => w.strategy ?? '—' },
                { id: 'restarts', header: t('ha.restarts'), numeric: true, value: (w) => w.restarts, cell: (w) => w.restarts },
                {
                  id: 'flags',
                  header: t('ha.attention'),
                  value: (w) => w.flags.length,
                  cell: (w) =>
                    w.flags.length ? (
                      <div className="row" style={{ gap: 4 }}>
                        {w.flags.map((f) => (
                          <Badge key={f} tone={FLAG_TONE[f] ?? 'muted'} title={t(`ha.flagHelp.${f}`)}>
                            {t(`ha.flag.${f}`)}
                          </Badge>
                        ))}
                      </div>
                    ) : (
                      <Badge tone="ok">{t('ha.allGood')}</Badge>
                    ),
                },
              ]}
            />
          </Card>
          <div className="section" style={{ marginTop: 14 }}>
            <Card title={t('ha.nodeHealth')}>
              <div className="row">
                {q.data.nodes.map((n) => (
                  <Link key={n.name} to={resourceLink('Node', null, n.name)!} className="card" style={{ padding: '8px 12px', textDecoration: 'none', color: 'inherit' }}>
                    <div className="row">
                      <strong>{n.name}</strong> <HealthBadge health={n.health} />
                    </div>
                    <div className="small muted">
                      {n.roles.join(', ')}
                      {n.unschedulable ? ` · ${t('ha.cordoned')}` : ''}
                      {n.pressures.length ? ` · ${n.pressures.join(', ')}` : ''}
                    </div>
                  </Link>
                ))}
              </div>
            </Card>
          </div>
        </>
      )}
    </>
  );
}
