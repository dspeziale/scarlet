import { useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import type { ResourceList } from '@/api/types';
import { useApi } from '@/hooks/api';
import { DataTable } from '@/components/DataTable';
import { ErrorPanel } from '@/components/ErrorPanel';
import { Card, Loading } from '@/components/ui';
import { resourceLink } from '@/utils/links';
import { columnsFor } from '../columns';

/** Pods belonging to a workload (via the top owner computed by the backend) or running on a node. */
export function PodsTab({ kind, name, namespace }: { kind: string; name: string; namespace: string | null }) {
  const { t } = useTranslation(['k8s', 'common']);
  const navigate = useNavigate();
  const q = useApi<ResourceList>('/k8s/pods', { namespace: namespace ?? undefined });
  const rows = useMemo(() => {
    const items = q.data?.items ?? [];
    if (kind === 'Node') return items.filter((p) => p.node === name);
    return items.filter((p) => {
      const o = p.owner as { kind: string; name: string } | null;
      if (!o) return false;
      if (o.kind === kind && o.name === name) return true;
      // CronJob -> Job -> Pod: job names start with the cronjob name
      return kind === 'CronJob' && o.kind === 'Job' && o.name.startsWith(`${name}-`);
    });
  }, [q.data, kind, name]);
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorPanel error={q.error} onRetry={() => void q.refetch()} />;
  return (
    <Card flush>
      <DataTable
        rows={rows}
        rowKey={(r) => `${r.namespace}/${r.name}`}
        columns={columnsFor('pods', t, kind === 'Node')}
        onRowClick={(r) => navigate(resourceLink('Pod', r.namespace, r.name)!)}
        emptyText={t('common:noItems')}
      />
    </Card>
  );
}
