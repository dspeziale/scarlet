import { useTranslation } from 'react-i18next';
import { resPath } from '@/api/client';
import { useApi } from '@/hooks/api';
import { ErrorPanel } from '@/components/ErrorPanel';
import { Alert, Card, Empty, Loading, Progress } from '@/components/ui';
import { formatBytes, formatCpu, formatPercent } from '@/utils/format';

interface Row {
  pod: string;
  container: string;
  cpu: number | null;
  memory: number | null;
  cpuLimit: number | null;
  memoryLimit: number | null;
  cpuRequest: number | null;
  memoryRequest: number | null;
}

export function MetricsTab({ kindKey, namespace, name }: { kindKey: string; namespace: string | null; name: string }) {
  const { t } = useTranslation('k8s');
  const q = useApi<{ available: boolean; source: string; containers?: Row[]; node?: { cpu: number; memory: number } | null }>(
    `${resPath(kindKey, namespace, name)}/metrics`,
    undefined,
    { refetchInterval: 15_000 },
  );
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorPanel error={q.error} onRetry={() => void q.refetch()} />;
  const d = q.data!;
  if (!d.available) return <Alert tone="info" title={t('errors:metrics_unavailable.title')}>{t('detail.metricsUnavailable')}</Alert>;
  if (d.node !== undefined) {
    return d.node ? (
      <Card title={t('detail.usage')}>
        <p>CPU: <strong>{formatCpu(d.node.cpu)}</strong> · {t('col.memory')}: <strong>{formatBytes(d.node.memory)}</strong></p>
        <p className="small muted">metrics-server</p>
      </Card>
    ) : (
      <Empty>{t('detail.metricsUnavailable')}</Empty>
    );
  }
  const rows = d.containers ?? [];
  if (!rows.length) return <Empty>{t('common:noItems')}</Empty>;
  return (
    <Card title={`${t('detail.usage')} (metrics-server)`} flush>
      <table className="data">
        <thead>
          <tr>
            <th scope="col">Pod</th>
            <th scope="col">Container</th>
            <th scope="col">CPU</th>
            <th scope="col">{t('col.memory')}</th>
            <th scope="col" style={{ width: 220 }}>{t('col.memory')} / {t('detail.limit')}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const ratio = r.memoryLimit && r.memory !== null ? r.memory / r.memoryLimit : null;
            return (
              <tr key={`${r.pod}/${r.container}`}>
                <td className="mono small">{r.pod}</td>
                <td>{r.container}</td>
                <td>
                  {formatCpu(r.cpu)} <span className="small muted">/ {r.cpuLimit ? formatCpu(r.cpuLimit) : t('detail.noLimit')}</span>
                </td>
                <td>
                  {formatBytes(r.memory)} <span className="small muted">/ {r.memoryLimit ? formatBytes(r.memoryLimit) : t('detail.noLimit')}</span>
                </td>
                <td>
                  {ratio !== null ? (
                    <div className="stack" style={{ gap: 2 }}>
                      <Progress ratio={ratio} label={`${r.container} memory`} />
                      <span className="small muted">{formatPercent(ratio)}</span>
                    </div>
                  ) : (
                    <span className="small muted">{t('detail.noLimit')}</span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </Card>
  );
}
