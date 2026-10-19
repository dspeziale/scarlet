import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Ban, CircleOff, Database, Eraser, PlayCircle, Sparkles, Square } from 'lucide-react';
import { post } from '@/api/client';
import type { ResourceList } from '@/api/types';
import { useAuth } from '@/auth/AuthContext';
import { useAction, useApi, useOperation } from '@/hooks/api';
import { Alert, Badge, Card, Field, HealthBadge, Loading, PageHeader } from '@/components/ui';
import { DataTable } from '@/components/DataTable';
import { ErrorPanel } from '@/components/ErrorPanel';
import { HelpLink } from '@/components/HelpLink';
import { ConfirmDialog, Dialog } from '@/components/Dialog';
import { useResourceOps } from '@/components/ResourceOps';
import { formatDate } from '@/utils/format';
import { resourceLink } from '@/utils/links';
import '@/styles/pages-b.css';

interface PlanPod {
  name: string;
  namespace: string;
  owner: string | null;
  action: 'evict' | 'skip' | 'blocked';
  reason: string | null;
}

interface DrainResult {
  node: string;
  results: Record<string, string>;
  timedOut: boolean;
  cancelled: boolean;
  remaining: string[];
  skipped: string[];
}

const ACTION_TONE = { evict: 'info', skip: 'muted', blocked: 'err' } as const;

export default function Maintenance() {
  const { t } = useTranslation('operations');
  const { can } = useAuth();
  const nodes = useApi<ResourceList>('/k8s/nodes');
  const pods = useApi<ResourceList>('/k8s/pods');
  const ops = useResourceOps();
  const [drainNode, setDrainNode] = useState<string | null>(null);
  const [opId, setOpId] = useState<string | null>(null);
  const op = useOperation(opId);
  const [appConfirm, setAppConfirm] = useState<'housekeeping' | 'cache' | 'db' | null>(null);
  const [appResult, setAppResult] = useState<{ kind: string; data: Record<string, unknown> } | null>(null);

  const podCount = useMemo(() => {
    const m: Record<string, number> = {};
    for (const p of pods.data?.items ?? []) {
      const n = p.node as string | undefined;
      if (n && p.health !== 'completed') m[n] = (m[n] ?? 0) + 1;
    }
    return m;
  }, [pods.data]);

  const appAction = useAction(
    async (kind: 'housekeeping' | 'cache' | 'db') => {
      const path = kind === 'housekeeping' ? '/maintenance/housekeeping' : kind === 'cache' ? '/maintenance/cache/clear' : '/maintenance/database/optimize';
      return { kind, data: await post<Record<string, unknown>>(path) };
    },
    {
      success: t('maint.done'),
      onSuccess: (r) => {
        setAppResult(r);
        setAppConfirm(null);
      },
    },
  );
  const cancel = useAction((id: string) => post(`/operations/${id}/cancel`), { success: t('maint.cancelRequested') });

  const drainResult = op.data?.result as DrainResult | undefined;

  return (
    <>
      <PageHeader
        title={t('maint.title')}
        subtitle={t('maint.subtitle')}
        help={
          <div className="row">
            <HelpLink slug="proc-manutenzione-nodo" />
            <HelpLink slug="node" label={t('common:helpWhatIs', { kind: 'Node' })} />
          </div>
        }
      />
      <Alert tone="info" title={t('maint.howTitle')}>
        <ol style={{ margin: 0, paddingLeft: 18 }}>
          <li>{t('maint.how1')}</li>
          <li>{t('maint.how2')}</li>
          <li>{t('maint.how3')}</li>
        </ol>
      </Alert>
      {!can('nodes.maintain') && <Alert tone="warn">{t('maint.nodesAdminOnly')}</Alert>}
      <Card title={t('maint.nodes')} flush>
        {nodes.isLoading && <Loading />}
        {nodes.error && (
          <div style={{ padding: 12 }}>
            <ErrorPanel error={nodes.error} onRetry={() => void nodes.refetch()} />
          </div>
        )}
        {nodes.data && (
          <DataTable
            rows={nodes.data.items}
            rowKey={(r) => r.name}
            caption={t('maint.nodes')}
            columns={[
              { id: 'name', header: t('common:name'), cell: (r) => <Link to={resourceLink('Node', null, r.name)!}>{r.name}</Link>, value: (r) => r.name },
              { id: 'status', header: t('common:status'), cell: (r) => <HealthBadge health={r.health} label={String(r.status)} />, value: (r) => String(r.status) },
              { id: 'roles', header: t('maint.roles'), cell: (r) => ((r.roles as string[]) ?? []).join(', '), value: (r) => ((r.roles as string[]) ?? []).join(',') },
              {
                id: 'sched',
                header: t('maint.scheduling'),
                cell: (r) => (r.unschedulable ? <Badge tone="warn">{t('maint.cordoned')}</Badge> : <Badge tone="ok">{t('maint.schedulable')}</Badge>),
                value: (r) => (r.unschedulable ? 1 : 0),
              },
              { id: 'pods', header: t('maint.pods'), cell: (r) => podCount[r.name] ?? 0, value: (r) => podCount[r.name] ?? 0, numeric: true },
              {
                id: 'act',
                header: <span className="sr-only">{t('common:actions')}</span>,
                cell: (r) =>
                  can('nodes.maintain') ? (
                    <span className="row">
                      {r.unschedulable ? (
                        <button className="btn sm" onClick={() => ops.open('uncordon', { key: 'nodes', kind: 'Node', name: r.name })}>
                          <PlayCircle size={14} /> Uncordon
                        </button>
                      ) : (
                        <button className="btn sm" onClick={() => ops.open('cordon', { key: 'nodes', kind: 'Node', name: r.name })}>
                          <Ban size={14} /> Cordon
                        </button>
                      )}
                      <button className="btn sm" onClick={() => setDrainNode(r.name)} disabled={op.data?.status === 'running'}>
                        <CircleOff size={14} /> Drain
                      </button>
                    </span>
                  ) : null,
              },
            ]}
          />
        )}
      </Card>

      {op.data && (
        <div className="section" style={{ marginTop: 14 }}>
          <Card
            title={t('maint.drainProgress', { node: op.data.target })}
            actions={
              op.data.status === 'running' ? (
                <button className="btn sm" onClick={() => void cancel.run(op.data!.id)} disabled={cancel.busy}>
                  <Square size={14} /> {t('maint.cancel')}
                </button>
              ) : null
            }
          >
            <div aria-live="polite">
              <Badge tone={op.data.status === 'succeeded' && !drainResult?.timedOut ? 'ok' : op.data.status === 'running' ? 'info' : 'warn'}>
                {t(`maint.opStatus.${op.data.status}`)}
              </Badge>
              <ul className="step-log" style={{ marginTop: 8 }}>
                {op.data.steps.map((s, i) => (
                  <li key={i}>
                    {formatDate(s.ts)} · {t(`maint.step.${s.step}`, { pod: s.pod, node: s.node, message: s.message, defaultValue: s.step })}
                  </li>
                ))}
              </ul>
              {op.data.error && <ErrorPanel error={Object.assign(new Error(op.data.error.message), op.data.error)} />}
              {drainResult && (
                <Alert tone={drainResult.remaining.length ? 'warn' : 'ok'} title={t('maint.drainResult')}>
                  <p>
                    {t('maint.evicted', { count: Object.values(drainResult.results).filter((v) => v === 'evicted' || v === 'gone').length })} ·{' '}
                    {t('maint.skipped', { count: drainResult.skipped.length })}
                  </p>
                  {drainResult.remaining.length > 0 && <p>{t('maint.remaining', { pods: drainResult.remaining.join(', ') })}</p>}
                  {drainResult.timedOut && <p>{t('maint.timedOut')}</p>}
                  {drainResult.cancelled && <p>{t('maint.cancelled')}</p>}
                  <p className="small">{t('maint.afterDrain')}</p>
                </Alert>
              )}
            </div>
          </Card>
        </div>
      )}

      {can('maintenance.run') && (
        <div className="section" style={{ marginTop: 14 }}>
          <Card title={t('maint.appTitle')}>
            <p className="small muted">{t('maint.appExplain')}</p>
            <div className="grid cols-3">
              {(
                [
                  ['housekeeping', <Eraser key="i" size={16} />],
                  ['cache', <Sparkles key="i" size={16} />],
                  ['db', <Database key="i" size={16} />],
                ] as const
              ).map(([k, icon]) => (
                <div key={k} className="card" style={{ padding: 12 }}>
                  <h3 className="row">
                    {icon} {t(`maint.app.${k}.title`)}
                  </h3>
                  <p className="small">{t(`maint.app.${k}.text`)}</p>
                  <button className="btn sm" onClick={() => setAppConfirm(k)}>
                    {t(`maint.app.${k}.button`)}
                  </button>
                </div>
              ))}
            </div>
            {appResult && (
              <Alert tone="ok" title={t(`maint.app.${appResult.kind}.title`)}>
                <code>{JSON.stringify(appResult.data)}</code>
              </Alert>
            )}
          </Card>
        </div>
      )}

      {drainNode && (
        <DrainDialog
          node={drainNode}
          onClose={() => setDrainNode(null)}
          onStarted={(id) => {
            setOpId(id);
            setDrainNode(null);
          }}
        />
      )}
      {appConfirm && (
        <ConfirmDialog
          spec={{
            title: t(`maint.app.${appConfirm}.title`),
            operation: t(`maint.app.${appConfirm}.button`),
            resource: 'Scarlet',
            consequences: [t(`maint.app.${appConfirm}.cons`)],
            risk: 'low',
          }}
          busy={appAction.busy}
          onClose={() => setAppConfirm(null)}
          onConfirm={() => void appAction.run(appConfirm)}
        />
      )}
      {ops.dialog}
    </>
  );
}

function DrainDialog({ node, onClose, onStarted }: { node: string; onClose: () => void; onStarted: (opId: string) => void }) {
  const { t } = useTranslation('operations');
  const plan = useApi<{ node: string; pods: PlanPod[] }>(`/k8s/nodes/_/${encodeURIComponent(node)}/drain-plan`, undefined, { refetchInterval: false });
  const [forceUnmanaged, setForceUnmanaged] = useState(false);
  const [deleteEmptydir, setDeleteEmptydir] = useState(false);
  const [timeout, setTimeoutSec] = useState(600);
  const [typed, setTyped] = useState('');
  const start = useAction(
    () =>
      post<{ operation: { id: string } }>(`/k8s/nodes/_/${encodeURIComponent(node)}/drain`, {
        confirm: typed,
        force_unmanaged: forceUnmanaged,
        delete_emptydir: deleteEmptydir,
        timeout_seconds: timeout,
      }),
    { success: t('maint.drainStarted', { node }), onSuccess: (r) => onStarted(r.operation.id) },
  );
  const pods = plan.data?.pods ?? [];
  const blocked = pods.filter((p) => p.action === 'blocked' && !((p.reason === 'unmanaged' && forceUnmanaged) || (p.reason === 'emptydir' && deleteEmptydir)));

  return (
    <Dialog
      wide
      title={t('maint.drainTitle', { node })}
      onClose={onClose}
      footer={
        <>
          <button className="btn" onClick={onClose}>
            {t('common:cancel')}
          </button>
          <button className="btn danger" disabled={typed !== node || blocked.length > 0 || start.busy || !plan.data} onClick={() => void start.run()}>
            {start.busy && <span className="spinner" aria-hidden="true" />} {t('maint.drainButton')}
          </button>
        </>
      }
    >
      <p>{t('maint.drainExplain')}</p>
      {plan.isLoading && <Loading />}
      {plan.error && <ErrorPanel error={plan.error} onRetry={() => void plan.refetch()} />}
      {plan.data && (
        <>
          <DataTable
            rows={pods}
            rowKey={(p) => `${p.namespace}/${p.name}`}
            pageSize={20}
            caption={t('maint.planTitle')}
            columns={[
              { id: 'pod', header: 'Pod', cell: (p) => `${p.namespace}/${p.name}`, value: (p) => `${p.namespace}/${p.name}` },
              { id: 'owner', header: t('maint.owner'), cell: (p) => p.owner ?? '—', value: (p) => p.owner ?? '' },
              { id: 'act', header: t('maint.planAction'), cell: (p) => <Badge tone={ACTION_TONE[p.action]}>{t(`maint.action.${p.action}`)}</Badge>, value: (p) => p.action },
              { id: 'reason', header: t('maint.reason'), cell: (p) => (p.reason ? t(`maint.reasons.${p.reason}`) : '—') },
            ]}
          />
          <fieldset style={{ marginTop: 12 }}>
            <legend>{t('maint.options')}</legend>
            <label className="checkbox">
              <input type="checkbox" checked={forceUnmanaged} onChange={(e) => setForceUnmanaged(e.target.checked)} />
              {t('maint.forceUnmanaged')}
            </label>
            <label className="checkbox" style={{ display: 'flex' }}>
              <input type="checkbox" checked={deleteEmptydir} onChange={(e) => setDeleteEmptydir(e.target.checked)} />
              {t('maint.deleteEmptydir')}
            </label>
            <Field label={t('maint.timeout')} htmlFor="drain-timeout">
              <input id="drain-timeout" className="input" type="number" min={30} max={3600} value={timeout} onChange={(e) => setTimeoutSec(Math.min(3600, Math.max(30, Number(e.target.value) || 600)))} />
            </Field>
          </fieldset>
          {blocked.length > 0 && <Alert tone="err">{t('maint.blocked', { count: blocked.length })}</Alert>}
          <Alert tone="warn" title={t('maint.drainRiskTitle')}>
            {t('maint.drainRisk')}
          </Alert>
          <Field label={t('common:confirmDialog.typeToConfirm', { value: node })} htmlFor="drain-confirm">
            <input id="drain-confirm" className="input" value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" />
          </Field>
        </>
      )}
    </Dialog>
  );
}
