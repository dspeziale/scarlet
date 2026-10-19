import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { ArrowRight } from 'lucide-react';
import type { Graph, GraphNode } from '@/api/types';
import { useApi } from '@/hooks/api';
import { ErrorPanel } from '@/components/ErrorPanel';
import { Empty, HEALTH_TONE, Loading } from '@/components/ui';
import { resPath } from '@/api/client';
import { resourceLink } from '@/utils/links';

// Columns read left to right like the traffic/ownership flow:
// Ingress → Service → Deployment → ReplicaSet → Pod → (Node, PVC, ConfigMap, Secret…)
const COLUMN_OF: Record<string, number> = {
  Ingress: 0, Service: 0, CronJob: 1, Deployment: 1, StatefulSet: 1, DaemonSet: 1, Job: 2, ReplicaSet: 2,
  Pod: 3, Node: 4, PersistentVolumeClaim: 4, ConfigMap: 4, Secret: 4, PersistentVolume: 5, StorageClass: 5,
};
const COLUMN_TITLES = ['entry', 'controller', 'workload', 'pods', 'infra', 'infra'];

export function RelationsView({ kindKey, namespace, name }: { kindKey: string; namespace: string | null; name: string }) {
  const { t } = useTranslation('k8s');
  const q = useApi<Graph>(`${resPath(kindKey, namespace, name)}/relations`);
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorPanel error={q.error} onRetry={() => void q.refetch()} />;
  const g = q.data!;
  if (g.nodes.length <= 1) return <Empty>{t('relations.empty')}</Empty>;
  const cols: GraphNode[][] = [[], [], [], [], [], []];
  for (const n of g.nodes) cols[COLUMN_OF[n.kind] ?? 4].push(n);
  const used = cols.map((c, i) => ({ c, i })).filter((x) => x.c.length);
  const label = (id: string) => g.nodes.find((n) => n.id === id);
  return (
    <div className="stack">
      <p className="muted">{t('relations.help')}</p>
      <div className="graph" role="list" aria-label={t('relations.title')}>
        {used.map(({ c, i }, idx) => (
          <div key={i} style={{ display: 'flex', gap: 28 }}>
            {idx > 0 && <ArrowRight className="graph-arrow" aria-hidden="true" />}
            <div className="graph-col">
              <div className="graph-col-title">{t(`relations.columns.${COLUMN_TITLES[i]}`)}</div>
              {c.map((n) => {
                const link = !n.missing ? resourceLink(n.kind, n.namespace, n.name) : null;
                const body = (
                  <>
                    <div className="k">{n.kind}{n.missing ? ` · ${t('relations.missing')}` : ''}</div>
                    <div className="n">{n.name}</div>
                  </>
                );
                return (
                  <div key={n.id} role="listitem" className={`graph-node tone-${HEALTH_TONE[n.health]} ${n.root ? 'root' : ''} ${n.missing ? 'missing' : ''}`}>
                    {link && !n.root ? <Link to={link} style={{ color: 'inherit' }}>{body}</Link> : body}
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>
      <details>
        <summary>{t('detail.technical')}</summary>
        <ul className="small">
          {g.edges.map((e) => (
            <li key={`${e.from}-${e.to}-${e.type}`}>
              {label(e.from)?.kind}/{label(e.from)?.name} <em>{t(`relations.edge.${e.type}`)}</em> {label(e.to)?.kind}/{label(e.to)?.name}
            </li>
          ))}
        </ul>
      </details>
    </div>
  );
}
