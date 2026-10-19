import { useMemo } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { RefreshCw, Rocket } from 'lucide-react';
import type { ResourceList, ResourceSummary } from '@/api/types';
import { useApi } from '@/hooks/api';
import { useAuth } from '@/auth/AuthContext';
import { DataTable } from '@/components/DataTable';
import { ErrorPanel } from '@/components/ErrorPanel';
import { KindHelp } from '@/components/HelpLink';
import { NamespaceSelect } from '@/components/NamespaceSelect';
import { Card, Loading, PageHeader } from '@/components/ui';
import { useResourceOps } from '@/components/ResourceOps';
import { KIND_GUIDE } from '@/guide';
import { resourceLink } from '@/utils/links';
import { columnsFor } from './columns';
import { templateFor } from '../operations/templates';
import { Plus } from 'lucide-react';

const WORKLOADS = new Set(['deployments', 'statefulsets', 'daemonsets']);
const CLUSTER_SCOPED = new Set(['nodes', 'namespaces', 'persistentvolumes', 'storageclasses']);

export default function ResourceListPage() {
  const { kind = 'pods' } = useParams();
  const { t } = useTranslation(['k8s', 'nav', 'common']);
  const { can } = useAuth();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const namespace = params.get('namespace') ?? '';
  const healthFilter = params.get('health') ?? '';
  const nodeFilter = params.get('node') ?? '';
  const namespaced = !CLUSTER_SCOPED.has(kind);
  const list = useApi<ResourceList>(`/k8s/${kind}`, { namespace: namespaced ? namespace || undefined : undefined });
  const ops = useResourceOps();

  const kindName = list.data?.kind.kind ?? '';
  const rows = useMemo(() => {
    let items = (list.data?.items ?? []) as (ResourceSummary & Record<string, unknown>)[];
    if (healthFilter === 'problems') items = items.filter((r) => !['healthy', 'completed', 'suspended'].includes(r.health));
    else if (healthFilter) items = items.filter((r) => r.health === healthFilter);
    if (nodeFilter) items = items.filter((r) => r.node === nodeFilter);
    return items;
  }, [list.data, healthFilter, nodeFilter]);

  const columns = useMemo(() => {
    const cols = columnsFor(kind, t, namespaced);
    if (WORKLOADS.has(kind) || kind === 'pods') {
      cols.push({
        id: 'ops',
        header: <span className="sr-only">{t('common:actions')}</span>,
        cell: (r) => (
          <div className="row" style={{ flexWrap: 'nowrap' }}>
            {kind !== 'daemonsets' && kind !== 'pods' && can('workloads.scale') && (
              <button type="button" className="btn sm" onClick={() => ops.open('scale', { key: kind, kind: kindName, name: r.name, namespace: r.namespace, replicas: r.replicas as number })}>
                {t('action.scale')}
              </button>
            )}
            {can('workloads.restart') && (
              <button
                type="button"
                className="btn sm"
                onClick={() => ops.open('restart', { key: kind, kind: kindName, name: r.name, namespace: r.namespace, managed: kind === 'pods' ? !!r.owner : undefined })}
              >
                {t('action.restart')}
              </button>
            )}
            {kind === 'pods' && can('logs.read') && (
              <Link className="btn sm" to={`${resourceLink('Pod', r.namespace, r.name)}?tab=logs`}>
                {t('action.logs')}
              </Link>
            )}
          </div>
        ),
      });
    }
    return cols;
  }, [kind, t, namespaced, can, ops, kindName]);

  const setParam = (k: string, v: string) => {
    const next = new URLSearchParams(params);
    if (v) next.set(k, v);
    else next.delete(k);
    setParams(next, { replace: true });
  };

  return (
    <>
      <PageHeader
        title={t(`nav:${kind}`, { defaultValue: kindName || kind })}
        subtitle={kindName ? t(`kinds.${kindName}.simple`, { defaultValue: '' }) : undefined}
        help={kindName ? <KindHelp kind={kindName} slug={KIND_GUIDE[kindName]} /> : null}
        actions={
          <>
            {kind === 'deployments' && can('workloads.deploy') && (
              <Link className="btn primary" to="/operations/deploy">
                <Rocket size={16} /> {t('nav:deploy')}
              </Link>
            )}
            {(() => {
              const tpl = templateFor(kind);
              if (!tpl || !(tpl.adminOnly ? can('resources.apply') : can('workloads.deploy'))) return null;
              const q = new URLSearchParams({ template: kind, ...(namespace && tpl.namespaced ? { namespace } : {}) });
              return (
                <Link className="btn primary" to={`/operations/yaml?${q.toString()}`}>
                  <Plus size={16} /> {t('list.create', { kind: tpl.kind })}
                </Link>
              );
            })()}
            <button type="button" className="btn" onClick={() => void list.refetch()} disabled={list.isFetching}>
              <RefreshCw size={16} /> {t('common:refresh')}
            </button>
          </>
        }
      />
      {list.error && <ErrorPanel error={list.error} onRetry={() => void list.refetch()} />}
      {list.isLoading && <Loading />}
      {list.data && (
        <Card flush>
          <DataTable
            rows={rows}
            rowKey={(r) => `${r.namespace ?? ''}/${r.name}/${r.uid ?? ''}`}
            columns={columns}
            caption={t(`nav:${kind}`, { defaultValue: kind })}
            initialSort={kind === 'events' ? { id: 'last', dir: 'asc' } : { id: 'name', dir: 'asc' }}
            onRowClick={kind === 'events' ? undefined : (r) => navigate(resourceLink(kindName, r.namespace, r.name) ?? '#')}
            toolbar={
              <>
                {namespaced && <NamespaceSelect value={namespace} onChange={(v) => setParam('namespace', v)} />}
                {kind !== 'events' && (
                  <select className="input sm" value={healthFilter} onChange={(e) => setParam('health', e.target.value)} aria-label={t('list.filterHealth')}>
                    <option value="">{t('list.filterHealth')}: {t('common:all')}</option>
                    <option value="problems">{t('list.onlyProblems')}</option>
                    {['healthy', 'degraded', 'failed', 'pending', 'progressing', 'completed', 'suspended'].map((h) => (
                      <option key={h} value={h}>
                        {t(`common:health.${h}`)}
                      </option>
                    ))}
                  </select>
                )}
                {nodeFilter && (
                  <button type="button" className="btn sm" onClick={() => setParam('node', '')}>
                    {t('list.nodeFilter', { node: nodeFilter })} ✕
                  </button>
                )}
                {!namespaced && <span className="small muted">{t('list.notNamespaced')}</span>}
              </>
            }
          />
        </Card>
      )}
      {ops.dialog}
    </>
  );
}
