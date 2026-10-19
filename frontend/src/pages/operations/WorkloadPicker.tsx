import { useMemo, type ReactNode } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useQueries } from '@tanstack/react-query';
import { api } from '@/api/client';
import type { ResourceList, ResourceSummary } from '@/api/types';
import { Card, HealthBadge } from '@/components/ui';
import { DataTable } from '@/components/DataTable';
import { ErrorPanel } from '@/components/ErrorPanel';
import { NamespaceSelect } from '@/components/NamespaceSelect';
import { Loading } from '@/components/ui';
import { formatAge } from '@/utils/format';
import { resourceLink } from '@/utils/links';

export interface WorkloadRow extends ResourceSummary {
  key: string;
}

/** Table of workloads of the given kinds (deployments, statefulsets, daemonsets) with namespace filter. */
export function WorkloadPicker({
  kinds,
  action,
  extraColumn,
}: {
  kinds: string[];
  action: (row: WorkloadRow) => ReactNode;
  extraColumn?: { header: ReactNode; cell: (row: WorkloadRow) => ReactNode };
}) {
  const { t } = useTranslation('operations');
  const [params, setParams] = useSearchParams();
  const namespace = params.get('namespace') ?? '';
  const results = useQueries({
    queries: kinds.map((k) => ({
      queryKey: [`/k8s/${k}`, { namespace }],
      queryFn: ({ signal }: { signal: AbortSignal }) => api<ResourceList>(`/k8s/${k}`, { query: { namespace: namespace || undefined }, signal }),
    })),
  });
  const rows = useMemo<WorkloadRow[]>(
    () => results.flatMap((r, i) => (r.data?.items ?? []).map((it) => ({ ...it, key: kinds[i] }))),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [results.map((r) => r.dataUpdatedAt).join(','), kinds.join(',')],
  );
  const loading = results.some((r) => r.isLoading);
  const error = results.find((r) => r.error)?.error;

  return (
    <Card flush>
      {error && (
        <div style={{ padding: 12 }}>
          <ErrorPanel error={error} onRetry={() => results.forEach((r) => void r.refetch())} />
        </div>
      )}
      {loading ? (
        <Loading />
      ) : (
        <DataTable
          rows={rows}
          rowKey={(r) => `${r.key}/${r.namespace}/${r.name}`}
          caption={t('workloads')}
          toolbar={
            <NamespaceSelect
              value={namespace}
              onChange={(ns) => {
                const p = new URLSearchParams(params);
                if (ns) p.set('namespace', ns);
                else p.delete('namespace');
                setParams(p, { replace: true });
              }}
            />
          }
          columns={[
            { id: 'kind', header: t('kind'), cell: (r) => r.kind, value: (r) => r.kind },
            {
              id: 'name',
              header: t('common:name'),
              cell: (r) => <Link to={resourceLink(r.kind, r.namespace, r.name) ?? '#'}>{r.name}</Link>,
              value: (r) => r.name,
            },
            { id: 'ns', header: t('common:namespace'), cell: (r) => r.namespace, value: (r) => r.namespace ?? '' },
            { id: 'ready', header: t('ready'), cell: (r) => String(r.ready ?? '—'), value: (r) => Number(r.readyReplicas ?? 0), numeric: true },
            { id: 'health', header: t('common:status'), cell: (r) => <HealthBadge health={r.health} />, value: (r) => r.health },
            ...(extraColumn ? [{ id: 'extra', header: extraColumn.header, cell: extraColumn.cell }] : []),
            { id: 'age', header: t('common:age'), cell: (r) => formatAge(r.createdAt), value: (r) => r.createdAt ?? '' },
            { id: 'act', header: <span className="sr-only">{t('common:actions')}</span>, cell: action },
          ]}
        />
      )}
    </Card>
  );
}
