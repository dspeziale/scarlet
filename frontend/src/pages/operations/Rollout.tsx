import { useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { GitCompare, Pause, Play, RotateCw, Undo2 } from 'lucide-react';
import type { ResourceList, ResourceSummary } from '@/api/types';
import { useAuth } from '@/auth/AuthContext';
import { useApi } from '@/hooks/api';
import { Alert, Badge, Card, Empty, HealthBadge, KeyValue, Loading, PageHeader } from '@/components/ui';
import { ErrorPanel } from '@/components/ErrorPanel';
import { HelpLink } from '@/components/HelpLink';
import { Dialog } from '@/components/Dialog';
import { YamlDiff } from '@/components/YamlEditor';
import { useResourceOps } from '@/components/ResourceOps';
import { DataTable } from '@/components/DataTable';
import { NamespaceSelect } from '@/components/NamespaceSelect';
import { formatAge, formatDate } from '@/utils/format';
import '@/styles/pages-b.css';

interface Revision {
  revision: number;
  replicaSet: string;
  createdAt: string | null;
  images: string[];
  changeCause: string | null;
  replicas: number;
  current: boolean;
  templateYaml: string;
}

interface RolloutData {
  summary: ResourceSummary;
  revision: string | null;
  paused: boolean;
  history: Revision[];
  strategy: { type?: string; rollingUpdate?: { maxUnavailable?: string | number; maxSurge?: string | number } };
  conditions: { type: string; status: string; reason?: string; message?: string; lastUpdateTime?: string }[];
  complete: boolean;
}

export default function Rollout() {
  const { t } = useTranslation('operations');
  const { can } = useAuth();
  const [params, setParams] = useSearchParams();
  const namespace = params.get('namespace') ?? '';
  const name = params.get('name') ?? '';
  const [compare, setCompare] = useState<Revision | null>(null);
  const deployments = useApi<ResourceList>('/k8s/deployments', { namespace: namespace || undefined });
  const data = useApi<RolloutData>(name && namespace ? `/k8s/deployments/${encodeURIComponent(namespace)}/${encodeURIComponent(name)}/rollout` : null, undefined, {
    refetchInterval: (q) => (q.state.data && !q.state.data.complete && !q.state.data.paused ? 3000 : 30000),
  });
  const ops = useResourceOps();
  const target = { key: 'deployments', kind: 'Deployment', name, namespace };
  const current = data.data?.history.find((h) => h.current);

  const select = (ns: string, n: string) => {
    const p = new URLSearchParams();
    if (ns) p.set('namespace', ns);
    if (n) p.set('name', n);
    setParams(p, { replace: true });
  };

  const s = data.data?.summary;
  return (
    <>
      <PageHeader
        title={t('rollout.title')}
        subtitle={t('rollout.subtitle')}
        help={
          <div className="row">
            <HelpLink slug="rolling-update" />
            <HelpLink slug="rollback" />
            <HelpLink slug="proc-rollback" />
          </div>
        }
      />
      <Card>
        <div className="row">
          <label className="row small" htmlFor="ro-ns">
            {t('common:namespace')}
          </label>
          <NamespaceSelect id="ro-ns" value={namespace} onChange={(ns) => select(ns, '')} />
          <label className="small" htmlFor="ro-dep">
            {t('rollout.deployment')}
          </label>
          <select id="ro-dep" className="input sm" value={name ? `${namespace}/${name}` : ''} onChange={(e) => {
            const [ns, n] = e.target.value.split('/');
            select(ns ?? '', n ?? '');
          }}>
            <option value="">—</option>
            {(deployments.data?.items ?? []).map((d) => (
              <option key={`${d.namespace}/${d.name}`} value={`${d.namespace}/${d.name}`}>
                {d.namespace}/{d.name}
              </option>
            ))}
          </select>
        </div>
        {deployments.error && <ErrorPanel error={deployments.error} onRetry={() => void deployments.refetch()} />}
      </Card>

      {!name && <Empty>{t('rollout.pick')}</Empty>}
      {name && data.isLoading && <Loading />}
      {data.error && <ErrorPanel error={data.error} onRetry={() => void data.refetch()} />}
      {data.data && s && (
        <div className="stack" style={{ marginTop: 14 }}>
          <Card
            title={
              <span className="row">
                <Link to={`/k8s/deployments/${encodeURIComponent(namespace)}/${encodeURIComponent(name)}`}>{name}</Link>
                <HealthBadge health={s.health} />
                {data.data.paused && <Badge tone="muted">{t('rollout.paused')}</Badge>}
              </span>
            }
            actions={
              <>
                {can('workloads.rollout') &&
                  (data.data.paused ? (
                    <button className="btn sm" onClick={() => ops.open('resume', target)}>
                      <Play size={14} /> {t('rollout.resume')}
                    </button>
                  ) : (
                    <button className="btn sm" onClick={() => ops.open('pause', target)}>
                      <Pause size={14} /> {t('rollout.pause')}
                    </button>
                  ))}
                {can('workloads.restart') && (
                  <button className="btn sm" onClick={() => ops.open('restart', target)}>
                    <RotateCw size={14} /> {t('restart.action')}
                  </button>
                )}
              </>
            }
          >
            <div aria-live="polite">
              {data.data.complete ? (
                <Alert tone="ok">{t('rollout.complete', { revision: data.data.revision })}</Alert>
              ) : data.data.paused ? (
                <Alert tone="info">{t('rollout.pausedText')}</Alert>
              ) : (
                <Alert tone="warn">{t('rollout.inProgress', { ready: s.readyReplicas ?? 0, desired: s.replicas ?? 0 })}</Alert>
              )}
            </div>
            <div className="grid cols-2">
              <KeyValue
                items={[
                  [t('rollout.revision'), data.data.revision ?? '—'],
                  [t('ready'), String(s.ready ?? '—')],
                  [t('rollout.updated'), String(s.updatedReplicas ?? '—')],
                  [t('rollout.images'), ((s.images as string[]) ?? []).map((i) => <code key={i}>{i}</code>)],
                  [
                    t('rollout.strategy'),
                    data.data.strategy.type === 'RollingUpdate'
                      ? t('rollout.rolling', {
                          maxUnavailable: data.data.strategy.rollingUpdate?.maxUnavailable ?? '25%',
                          maxSurge: data.data.strategy.rollingUpdate?.maxSurge ?? '25%',
                        })
                      : t('rollout.recreate'),
                  ],
                ]}
              />
              <div>
                <h3 className="small">{t('rollout.conditions')}</h3>
                <ul className="check-list small">
                  {data.data.conditions.map((c) => (
                    <li key={c.type}>
                      <Badge tone={c.status === 'True' ? 'ok' : 'warn'}>{c.type}</Badge>
                      <span>
                        {c.reason} {c.message ? `— ${c.message}` : ''}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          </Card>

          <Card title={t('rollout.history')} flush>
            <DataTable
              rows={data.data.history}
              rowKey={(r) => String(r.revision)}
              initialSort={{ id: 'rev', dir: 'desc' }}
              caption={t('rollout.history')}
              columns={[
                { id: 'rev', header: t('rollout.revision'), cell: (r) => <strong>{r.revision}</strong>, value: (r) => r.revision, numeric: true },
                { id: 'img', header: t('rollout.images'), cell: (r) => r.images.map((i) => <div key={i}><code>{i}</code></div>), value: (r) => r.images.join(' ') },
                { id: 'cause', header: t('rollout.changeCause'), cell: (r) => r.changeCause ?? '—', value: (r) => r.changeCause ?? '' },
                { id: 'created', header: t('common:created'), cell: (r) => <span title={formatDate(r.createdAt)}>{formatAge(r.createdAt)}</span>, value: (r) => r.createdAt ?? '' },
                { id: 'rep', header: t('rollout.replicas'), cell: (r) => r.replicas, numeric: true },
                { id: 'cur', header: '', cell: (r) => (r.current ? <Badge tone="ok">{t('rollout.current')}</Badge> : null) },
                {
                  id: 'act',
                  header: <span className="sr-only">{t('common:actions')}</span>,
                  cell: (r) =>
                    r.current ? null : (
                      <span className="row">
                        <button className="btn sm" onClick={() => setCompare(r)} disabled={!current}>
                          <GitCompare size={14} /> {t('rollout.compare')}
                        </button>
                        {can('workloads.rollout') && (
                          <button className="btn sm" disabled={data.data!.paused} title={data.data!.paused ? t('rollout.resumeFirst') : undefined} onClick={() => ops.open('rollback', { ...target, revision: r.revision })}>
                            <Undo2 size={14} /> {t('rollout.rollbackTo')}
                          </button>
                        )}
                      </span>
                    ),
                },
              ]}
            />
          </Card>
          <Alert tone="info" title={t('rollout.explainTitle')}>
            <p>{t('rollout.explain1')}</p>
            <p>{t('rollout.explain2')}</p>
          </Alert>
        </div>
      )}
      {compare && current && (
        <Dialog wide title={t('rollout.compareTitle', { a: current.revision, b: compare.revision })} onClose={() => setCompare(null)}>
          <p className="small muted">{t('rollout.compareHint', { a: current.revision, b: compare.revision })}</p>
          <YamlDiff original={current.templateYaml} modified={compare.templateYaml} />
        </Dialog>
      )}
      {ops.dialog}
    </>
  );
}
