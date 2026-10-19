import type { TFunction } from 'i18next';
import { Link } from 'react-router-dom';
import type { Column } from '@/components/DataTable';
import type { ResourceSummary } from '@/api/types';
import { Badge, HealthBadge } from '@/components/ui';
import { formatAge, formatBytes, formatCpu, formatDuration } from '@/utils/format';
import { resourceLink } from '@/utils/links';

type R = ResourceSummary & Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

const chips = (items: unknown[] | undefined, max = 3) => {
  const list = (items ?? []) as string[];
  return (
    <>
      {list.slice(0, max).map((i) => (
        <span key={i} className="chip" title={i}>
          {i}
        </span>
      ))}
      {list.length > max && <span className="muted small">+{list.length - max}</span>}
    </>
  );
};

export function columnsFor(key: string, t: TFunction, namespaced: boolean): Column<R>[] {
  const name: Column<R> = { id: 'name', header: t('common:name'), cell: (r) => <strong className="mono">{r.name}</strong>, value: (r) => r.name };
  const ns: Column<R> = { id: 'namespace', header: t('common:namespace'), cell: (r) => r.namespace ?? '—', value: (r) => r.namespace ?? '' };
  const health: Column<R> = { id: 'health', header: t('common:status'), cell: (r) => <HealthBadge health={r.health} label={typeof r.status === 'string' ? r.status : undefined} />, value: (r) => (typeof r.status === 'string' ? r.status : r.health) };
  const age: Column<R> = { id: 'age', header: t('common:age'), cell: (r) => <span title={r.createdAt ?? ''}>{formatAge(r.createdAt)}</span>, value: (r) => r.createdAt ?? '' };
  const images: Column<R> = { id: 'images', header: t('k8s:col.images'), cell: (r) => chips(r.images, 2), value: (r) => (r.images ?? []).join(' ') };
  const base = (cols: Column<R>[]) => [name, ...(namespaced ? [ns] : []), ...cols, age];

  switch (key) {
    case 'pods':
      return base([
        health,
        { id: 'ready', header: t('k8s:col.ready'), cell: (r) => r.ready, value: (r) => r.ready },
        { id: 'restarts', header: t('k8s:col.restarts'), numeric: true, cell: (r) => (r.restarts > 0 ? <Badge tone={r.restarts > 5 ? 'warn' : 'muted'}>{r.restarts}</Badge> : 0), value: (r) => r.restarts },
        { id: 'node', header: t('k8s:col.node'), cell: (r) => (r.node ? <Link to={resourceLink('Node', null, r.node)!}>{r.node}</Link> : '—'), value: (r) => r.node ?? '' },
        { id: 'owner', header: t('k8s:col.owner'), cell: (r) => (r.owner ? `${r.owner.kind}/${r.owner.name}` : '—'), value: (r) => r.owner?.name ?? '' },
      ]);
    case 'deployments':
      return base([
        health,
        { id: 'ready', header: t('k8s:col.ready'), cell: (r) => r.ready, value: (r) => r.readyReplicas },
        { id: 'uptodate', header: t('k8s:col.upToDate'), numeric: true, cell: (r) => r.updatedReplicas, value: (r) => r.updatedReplicas },
        { id: 'available', header: t('k8s:col.available'), numeric: true, cell: (r) => r.availableReplicas, value: (r) => r.availableReplicas },
        images,
      ]);
    case 'statefulsets':
      return base([health, { id: 'ready', header: t('k8s:col.ready'), cell: (r) => r.ready, value: (r) => r.readyReplicas }, images]);
    case 'daemonsets':
      return base([
        health,
        { id: 'desired', header: t('k8s:col.desired'), numeric: true, cell: (r) => r.desired, value: (r) => r.desired },
        { id: 'ready', header: t('k8s:col.ready'), cell: (r) => r.ready, value: (r) => r.readyReplicas },
        images,
      ]);
    case 'replicasets':
      return base([health, { id: 'ready', header: t('k8s:col.ready'), cell: (r) => r.ready }, { id: 'rev', header: t('k8s:col.revision'), cell: (r) => r.revision ?? '—', value: (r) => Number(r.revision ?? 0) }, images]);
    case 'jobs':
      return base([
        health,
        { id: 'compl', header: t('k8s:col.completions'), cell: (r) => r.completions },
        { id: 'dur', header: t('k8s:col.duration'), cell: (r) => formatDuration(r.duration), value: (r) => r.duration ?? 0 },
      ]);
    case 'cronjobs':
      return base([
        health,
        { id: 'schedule', header: t('k8s:col.schedule'), cell: (r) => <code>{r.schedule}</code>, value: (r) => r.schedule },
        { id: 'active', header: t('k8s:col.active'), numeric: true, cell: (r) => r.active, value: (r) => r.active },
        { id: 'last', header: t('k8s:col.lastSchedule'), cell: (r) => formatAge(r.lastScheduleTime), value: (r) => r.lastScheduleTime ?? '' },
      ]);
    case 'services':
      return base([
        { id: 'type', header: t('k8s:col.type'), cell: (r) => <Badge tone="info">{r.type}</Badge>, value: (r) => r.type },
        { id: 'cip', header: t('k8s:col.clusterIP'), cell: (r) => <code>{r.clusterIP}</code>, value: (r) => r.clusterIP },
        { id: 'ext', header: t('k8s:col.external'), cell: (r) => chips(r.externalIPs), value: (r) => (r.externalIPs ?? []).join(' ') },
        { id: 'ports', header: t('k8s:col.ports'), cell: (r) => chips(r.ports, 4), value: (r) => (r.ports ?? []).join(' ') },
      ]);
    case 'ingresses':
      return base([
        health,
        { id: 'class', header: t('k8s:col.class'), cell: (r) => r.class ?? '—', value: (r) => r.class ?? '' },
        { id: 'hosts', header: t('k8s:col.hosts'), cell: (r) => chips(r.hosts), value: (r) => (r.hosts ?? []).join(' ') },
        { id: 'addr', header: t('k8s:col.addresses'), cell: (r) => chips(r.addresses), value: (r) => (r.addresses ?? []).join(' ') },
        { id: 'tls', header: t('k8s:col.tls'), cell: (r) => ((r.tls ?? []).length ? <Badge tone="ok">TLS</Badge> : <Badge tone="warn">HTTP</Badge>) },
      ]);
    case 'endpoints':
      return base([
        health,
        { id: 'ready', header: t('k8s:col.ready'), numeric: true, cell: (r) => r.ready, value: (r) => r.ready },
        { id: 'nready', header: t('k8s:col.notReady'), numeric: true, cell: (r) => r.notReady, value: (r) => r.notReady },
        { id: 'addr', header: t('k8s:col.addresses'), cell: (r) => chips(r.addresses, 4) },
      ]);
    case 'persistentvolumes':
      return base([
        health,
        { id: 'cap', header: t('k8s:col.capacity'), cell: (r) => r.capacity ?? '—', value: (r) => r.capacity },
        { id: 'am', header: t('k8s:col.accessModes'), cell: (r) => chips(r.accessModes) },
        { id: 'rp', header: t('k8s:col.reclaim'), cell: (r) => r.reclaimPolicy, value: (r) => r.reclaimPolicy },
        { id: 'claim', header: t('k8s:col.claim'), cell: (r) => r.claim ?? '—', value: (r) => r.claim ?? '' },
        { id: 'sc', header: t('k8s:col.storageClass'), cell: (r) => r.storageClass ?? '—', value: (r) => r.storageClass ?? '' },
      ]);
    case 'persistentvolumeclaims':
      return base([
        health,
        { id: 'vol', header: t('k8s:col.volume'), cell: (r) => r.volume ?? '—', value: (r) => r.volume ?? '' },
        { id: 'cap', header: t('k8s:col.capacity'), cell: (r) => r.capacity ?? '—', value: (r) => r.capacity },
        { id: 'am', header: t('k8s:col.accessModes'), cell: (r) => chips(r.accessModes) },
        { id: 'sc', header: t('k8s:col.storageClass'), cell: (r) => r.storageClass ?? '—', value: (r) => r.storageClass ?? '' },
      ]);
    case 'storageclasses':
      return base([
        { id: 'prov', header: t('k8s:col.provisioner'), cell: (r) => <code>{r.provisioner}</code>, value: (r) => r.provisioner },
        { id: 'rp', header: t('k8s:col.reclaim'), cell: (r) => r.reclaimPolicy },
        { id: 'bm', header: t('k8s:col.bindingMode'), cell: (r) => r.volumeBindingMode },
        { id: 'exp', header: t('k8s:col.expansion'), cell: (r) => (r.allowVolumeExpansion ? t('common:yes') : t('common:no')) },
        { id: 'def', header: t('k8s:col.default'), cell: (r) => (r.default ? <Badge tone="info">default</Badge> : '') },
      ]);
    case 'configmaps':
      return base([{ id: 'keys', header: t('k8s:col.keys'), cell: (r) => chips(r.keys, 4), value: (r) => r.keyCount }]);
    case 'secrets':
      return base([
        { id: 'type', header: t('k8s:col.type'), cell: (r) => <code>{r.type}</code>, value: (r) => r.type },
        { id: 'keys', header: t('k8s:col.keys'), numeric: true, cell: (r) => r.keyCount, value: (r) => r.keyCount },
      ]);
    case 'nodes':
      return base([
        health,
        { id: 'roles', header: t('k8s:col.roles'), cell: (r) => chips(r.roles), value: (r) => (r.roles ?? []).join(' ') },
        { id: 'cpu', header: t('k8s:col.cpu'), numeric: true, cell: (r) => formatCpu(r.cpu), value: (r) => r.cpu },
        { id: 'mem', header: t('k8s:col.memory'), numeric: true, cell: (r) => formatBytes(r.memory), value: (r) => r.memory },
        { id: 'ver', header: t('k8s:col.version'), cell: (r) => r.kubeletVersion, value: (r) => r.kubeletVersion },
        { id: 'ip', header: t('k8s:col.internalIP'), cell: (r) => <code>{r.internalIP}</code>, value: (r) => r.internalIP },
        { id: 'sched', header: '', cell: (r) => (r.unschedulable ? <Badge tone="warn">cordon</Badge> : null) },
      ]);
    case 'namespaces':
      return base([health]);
    case 'events':
      return [
        { id: 'type', header: t('k8s:col.type'), cell: (r) => <Badge tone={r.type === 'Warning' ? 'warn' : 'muted'}>{r.type}</Badge>, value: (r) => r.type },
        { id: 'reason', header: t('k8s:col.reason'), cell: (r) => <strong>{r.reason}</strong>, value: (r) => r.reason },
        {
          id: 'obj',
          header: t('k8s:col.object'),
          cell: (r) => {
            const link = resourceLink(r.object?.kind, r.object?.namespace, r.object?.name);
            const label = `${r.object?.kind}/${r.object?.name}`;
            return link ? <Link to={link}>{label}</Link> : label;
          },
          value: (r) => `${r.object?.kind}/${r.object?.name}`,
        },
        ns,
        { id: 'msg', header: t('k8s:col.message'), cell: (r) => <span className="small">{r.message}</span>, value: (r) => r.message },
        { id: 'count', header: t('k8s:col.count'), numeric: true, cell: (r) => r.count, value: (r) => r.count },
        { id: 'last', header: t('k8s:col.lastSeen'), cell: (r) => formatAge(r.lastTimestamp), value: (r) => r.lastTimestamp ?? '' },
      ];
    case 'poddisruptionbudgets':
      return base([
        health,
        { id: 'min', header: 'minAvailable', cell: (r) => String(r.minAvailable ?? '—') },
        { id: 'max', header: 'maxUnavailable', cell: (r) => String(r.maxUnavailable ?? '—') },
        { id: 'dis', header: t('k8s:col.disruptions'), numeric: true, cell: (r) => r.disruptionsAllowed, value: (r) => r.disruptionsAllowed },
      ]);
    case 'horizontalpodautoscalers':
      return base([
        { id: 'target', header: t('k8s:col.target'), cell: (r) => r.target },
        { id: 'min', header: t('k8s:col.min'), numeric: true, cell: (r) => r.minReplicas },
        { id: 'max', header: t('k8s:col.max'), numeric: true, cell: (r) => r.maxReplicas },
        { id: 'cur', header: t('k8s:col.current'), numeric: true, cell: (r) => r.currentReplicas ?? '—' },
      ]);
    default:
      return base([health]);
  }
}
