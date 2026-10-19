import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Eye, EyeOff } from 'lucide-react';
import type { ContainerRow, ResourceDetail } from '@/api/types';
import { get, resPath } from '@/api/client';
import { useAuth } from '@/auth/AuthContext';
import { Alert, Badge, Card, HealthBadge, KeyValue } from '@/components/ui';
import { ErrorPanel } from '@/components/ErrorPanel';
import { formatAge, formatBytes, formatCpu, formatDate } from '@/utils/format';
import { resourceLink } from '@/utils/links';

/* eslint-disable @typescript-eslint/no-explicit-any */
type Obj = Record<string, any>;

function Labels({ labels }: { labels?: Record<string, string> }) {
  const entries = Object.entries(labels ?? {});
  if (!entries.length) return <span className="muted">—</span>;
  return (
    <>
      {entries.map(([k, v]) => (
        <span key={k} className="chip" title={`${k}=${v}`}>
          {k}={v}
        </span>
      ))}
    </>
  );
}

export function ContainersTable({ containers }: { containers: ContainerRow[] }) {
  const { t } = useTranslation('k8s');
  return (
    <div className="table-wrap">
      <table className="data">
        <thead>
          <tr>
            <th scope="col">{t('common:name')}</th>
            <th scope="col">Image</th>
            <th scope="col">{t('detail.state')}</th>
            <th scope="col" className="num">{t('col.restarts')}</th>
            <th scope="col">{t('detail.request')} CPU / RAM</th>
            <th scope="col">{t('detail.limit')} CPU / RAM</th>
            <th scope="col">{t('detail.probes')}</th>
          </tr>
        </thead>
        <tbody>
          {containers.map((c) => {
            const last = (c.lastState?.terminated ?? null) as Obj | null;
            return (
              <tr key={c.name}>
                <td><strong className="mono">{c.name}</strong></td>
                <td><code className="small">{c.image}</code></td>
                <td>
                  <Badge tone={c.ready ? 'ok' : c.state === 'waiting' ? 'err' : c.state === 'terminated' ? 'muted' : 'warn'}>
                    {c.reason ?? c.state}
                  </Badge>
                  {last && (
                    <div className="small muted">
                      {t('detail.lastTermination')}: {String(last.reason ?? '')} ({t('detail.exitCode', { code: last.exitCode })}) {formatAge(last.finishedAt)}
                    </div>
                  )}
                  {c.message && <div className="small muted">{c.message}</div>}
                </td>
                <td className="num">{c.restarts}</td>
                <td className="small">{c.requests.cpu ?? '—'} / {c.requests.memory ?? '—'}</td>
                <td className="small">{c.limits.cpu ?? <span className="muted">{t('detail.noLimit')}</span>} / {c.limits.memory ?? <span className="muted">{t('detail.noLimit')}</span>}</td>
                <td className="small">
                  {[c.readinessProbe && t('detail.readiness'), c.livenessProbe && t('detail.liveness'), c.startupProbe && t('detail.startup')].filter(Boolean).join(', ') || <Badge tone="warn">—</Badge>}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function Conditions({ obj }: { obj: Obj }) {
  const { t } = useTranslation('k8s');
  const conds: Obj[] = obj.status?.conditions ?? [];
  if (!conds.length) return null;
  return (
    <Card title={t('detail.conditions')} flush>
      <table className="data">
        <thead>
          <tr>
            <th scope="col">Type</th>
            <th scope="col">{t('common:status')}</th>
            <th scope="col">{t('col.reason')}</th>
            <th scope="col">{t('col.message')}</th>
            <th scope="col">{t('col.lastSeen')}</th>
          </tr>
        </thead>
        <tbody>
          {conds.map((c) => (
            <tr key={c.type}>
              <td>{c.type}</td>
              <td><Badge tone={c.status === 'True' ? (['MemoryPressure', 'DiskPressure', 'PIDPressure', 'NetworkUnavailable', 'Failed'].includes(c.type) ? 'err' : 'ok') : c.status === 'False' ? (['MemoryPressure', 'DiskPressure', 'PIDPressure', 'NetworkUnavailable', 'Failed'].includes(c.type) ? 'ok' : 'warn') : 'muted'}>{c.status}</Badge></td>
              <td className="small">{c.reason ?? '—'}</td>
              <td className="small">{c.message ?? '—'}</td>
              <td className="small">{formatAge(c.lastTransitionTime ?? c.lastUpdateTime)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  );
}

function SecretValues({ data, kindKey }: { data: ResourceDetail; kindKey: string }) {
  const { t } = useTranslation('k8s');
  const { can } = useAuth();
  const [revealed, setRevealed] = useState<Record<string, string> | null>(null);
  const [error, setError] = useState<unknown>(null);
  const keys: string[] = (data.summary.keys as string[]) ?? [];
  const reveal = async () => {
    setError(null);
    try {
      const res = await get<ResourceDetail>(resPath(kindKey, data.summary.namespace, data.summary.name), { reveal: true });
      setRevealed((res.object.data as Record<string, string>) ?? {});
    } catch (e) {
      setError(e);
    }
  };
  const decode = (b64: string) => {
    try {
      const bin = atob(b64);
      return /^[\x09\x0a\x0d\x20-\x7e -￿]*$/.test(bin) ? new TextDecoder().decode(Uint8Array.from(bin, (c) => c.charCodeAt(0))) : t('detail.binary');
    } catch {
      return b64;
    }
  };
  return (
    <Card
      title={t('col.keys')}
      actions={
        can('secrets.read_values') ? (
          revealed ? (
            <button className="btn sm" onClick={() => setRevealed(null)}><EyeOff size={14} /> {t('detail.hide')}</button>
          ) : (
            <button className="btn sm" onClick={() => void reveal()}><Eye size={14} /> {t('detail.reveal')}</button>
          )
        ) : null
      }
    >
      <Alert tone={revealed ? 'warn' : 'info'}>{revealed ? t('detail.revealed') : t('detail.secretHidden')}</Alert>
      {error ? <ErrorPanel error={error} /> : null}
      <KeyValue items={keys.map((k) => [<code key={k}>{k}</code>, revealed ? <pre className="code" style={{ maxHeight: 160, margin: 0 }}>{decode(revealed[k] ?? '')}</pre> : '••••••••'])} />
    </Card>
  );
}

export function SimpleView({ data, kindKey }: { data: ResourceDetail; kindKey: string }) {
  const { t } = useTranslation('k8s');
  const s = data.summary as Obj;
  const o = data.object as Obj;
  const kind = data.kind.kind;
  const meta = o.metadata ?? {};
  const spec = o.spec ?? {};
  const common: [React.ReactNode, React.ReactNode][] = [
    [t('common:status'), <HealthBadge key="h" health={s.health} label={typeof s.status === 'string' ? s.status : undefined} />],
    ...(s.namespace ? ([[t('common:namespace'), <Link key="ns" to={resourceLink('Namespace', null, s.namespace)!}>{s.namespace}</Link>]] as [React.ReactNode, React.ReactNode][]) : []),
    [t('common:created'), `${formatDate(s.createdAt)} (${formatAge(s.createdAt)})`],
  ];
  const owner = (meta.ownerReferences ?? [])[0];
  if (owner) {
    const link = resourceLink(owner.kind, s.namespace, owner.name);
    common.push([t('detail.ownerLink'), link ? <Link to={link}>{owner.kind}/{owner.name}</Link> : `${owner.kind}/${owner.name}`]);
  }

  let specific: [React.ReactNode, React.ReactNode][] = [];
  let extra: React.ReactNode = null;
  let sentence: React.ReactNode = null;

  switch (kind) {
    case 'Deployment':
    case 'StatefulSet':
    case 'DaemonSet':
    case 'ReplicaSet': {
      const desired = kind === 'DaemonSet' ? s.desired : s.replicas;
      const ready = s.readyReplicas ?? 0;
      sentence = (
        <Alert tone={ready >= desired && desired > 0 ? 'ok' : desired === 0 ? 'info' : 'warn'}>
          <p>{t('detail.replicasSentence', { desired, ready })} {desired > 1 ? t('detail.haSentence') : desired === 1 ? t('detail.singleReplica') : ''}</p>
        </Alert>
      );
      specific = [
        [t('col.ready'), <strong key="r" style={{ fontSize: 16 }}>{s.ready}</strong>],
        ...(kind === 'Deployment'
          ? ([
              [t('detail.strategy'), `${spec.strategy?.type ?? '—'}${spec.strategy?.rollingUpdate ? ` (maxSurge ${spec.strategy.rollingUpdate.maxSurge}, maxUnavailable ${spec.strategy.rollingUpdate.maxUnavailable})` : ''}`],
              [t('col.revision'), s.revision ?? '—'],
              ...(s.paused ? [[t('detail.paused'), <Badge key="p" tone="warn">paused</Badge>]] : []),
            ] as [React.ReactNode, React.ReactNode][])
          : []),
        [t('detail.selector'), <Labels key="sel" labels={s.selector} />],
      ];
      const tmplContainers: Obj[] = spec.template?.spec?.containers ?? [];
      extra = (
        <Card title={t('detail.containers')} flush>
          <ContainersTable
            containers={tmplContainers.map((c) => ({
              name: c.name,
              image: c.image,
              ready: true,
              restarts: 0,
              state: 'template',
              lastState: {},
              ports: (c.ports ?? []).map((p: Obj) => p.containerPort),
              requests: c.resources?.requests ?? {},
              limits: c.resources?.limits ?? {},
              readinessProbe: !!c.readinessProbe,
              livenessProbe: !!c.livenessProbe,
              startupProbe: !!c.startupProbe,
            }))}
          />
        </Card>
      );
      break;
    }
    case 'Pod':
      specific = [
        [t('col.ready'), s.ready],
        [t('col.restarts'), s.restarts],
        [t('col.node'), s.node ? <Link key="n" to={resourceLink('Node', null, s.node)!}>{s.node}</Link> : '—'],
        [t('col.ip'), s.podIP ?? '—'],
        [t('col.qos'), s.qosClass ?? '—'],
      ];
      extra = (
        <Card title={t('detail.containers')} flush>
          <ContainersTable containers={s.containers as ContainerRow[]} />
        </Card>
      );
      break;
    case 'Service': {
      const headless = s.clusterIP === 'None';
      const help = t(`detail.serviceTypeHelp.${headless ? 'Headless' : s.type}`, { name: s.name, ns: s.namespace });
      sentence = <Alert tone="info">{help}</Alert>;
      specific = [
        [t('col.type'), s.type],
        [t('col.clusterIP'), <code key="ip">{s.clusterIP}</code>],
        [t('col.ports'), (s.ports as string[]).join(', ')],
        [t('col.external'), (s.externalIPs as string[]).join(', ') || '—'],
        [t('detail.selector'), <Labels key="sel" labels={s.selector} />],
      ];
      break;
    }
    case 'Ingress':
      specific = [
        [t('col.class'), s.class ?? '—'],
        [t('col.addresses'), (s.addresses as string[]).join(', ') || '—'],
        [t('col.tls'), (s.tls as string[]).join(', ') || <Badge key="t" tone="warn">HTTP</Badge>],
      ];
      extra = (
        <Card title={t('detail.rules')} flush>
          <table className="data">
            <thead><tr><th scope="col">Host</th><th scope="col">Path</th><th scope="col">Service</th><th scope="col">Port</th></tr></thead>
            <tbody>
              {(s.rules as Obj[]).map((r, i) => (
                <tr key={i}>
                  <td>{r.host}</td><td><code>{r.path}</code></td>
                  <td>{r.service ? <Link to={resourceLink('Service', s.namespace, r.service)!}>{r.service}</Link> : '—'}</td><td>{r.port}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      );
      break;
    case 'Endpoints':
      sentence = <Alert tone={s.ready > 0 ? 'ok' : 'warn'}>{s.ready + s.notReady > 0 ? t('detail.endpointsReady', { ready: s.ready, notReady: s.notReady }) : t('detail.noEndpoints')}</Alert>;
      specific = [[t('col.addresses'), (s.addresses as string[]).join(', ') || '—']];
      break;
    case 'Node':
      specific = [
        [t('col.roles'), (s.roles as string[]).join(', ')],
        [t('col.internalIP'), s.internalIP],
        [t('detail.allocatable'), `${formatCpu(s.cpu)} CPU · ${formatBytes(s.memory)} · ${s.pods} pod`],
        [t('detail.pressures'), (s.pressures as string[]).join(', ') || t('common:none')],
        [t('detail.taints'), (s.taints as string[]).length ? (s.taints as string[]).map((x) => <span key={x} className="chip">{x}</span>) : t('common:none')],
        [t('detail.unschedulable'), s.unschedulable ? t('common:yes') : t('common:no')],
        [t('detail.nodeInfo'), `${s.osImage} · kernel ${s.kernelVersion} · ${s.containerRuntime} · kubelet ${s.kubeletVersion}`],
      ];
      break;
    case 'PersistentVolumeClaim':
      sentence = <Alert tone={s.status === 'Bound' ? 'ok' : 'warn'}>{t(`detail.pvcStatusHelp.${s.status}`, { defaultValue: s.status })}</Alert>;
      specific = [
        [t('col.capacity'), s.capacity ?? '—'],
        [t('col.accessModes'), (s.accessModes as string[]).join(', ')],
        [t('col.storageClass'), s.storageClass ? <Link key="sc" to={resourceLink('StorageClass', null, s.storageClass)!}>{s.storageClass}</Link> : '—'],
        [t('col.volume'), s.volume ? <Link key="v" to={resourceLink('PersistentVolume', null, s.volume)!}>{s.volume}</Link> : '—'],
      ];
      break;
    case 'PersistentVolume':
      specific = [
        [t('col.capacity'), s.capacity], [t('col.accessModes'), (s.accessModes as string[]).join(', ')],
        [t('col.reclaim'), s.reclaimPolicy], [t('col.claim'), s.claim ?? '—'], [t('col.storageClass'), s.storageClass ?? '—'],
      ];
      break;
    case 'StorageClass':
      specific = [
        [t('col.provisioner'), <code key="p">{s.provisioner}</code>], [t('col.reclaim'), s.reclaimPolicy],
        [t('col.bindingMode'), s.volumeBindingMode], [t('col.expansion'), s.allowVolumeExpansion ? t('common:yes') : t('common:no')],
        [t('col.default'), s.default ? t('common:yes') : t('common:no')],
      ];
      break;
    case 'ConfigMap':
      extra = (
        <Card title={t('col.keys')}>
          <KeyValue items={Object.entries((o.data ?? {}) as Record<string, string>).map(([k, v]) => [<code key={k}>{k}</code>, <pre key={`${k}-v`} className="code" style={{ maxHeight: 200, margin: 0 }}>{v}</pre>])} />
        </Card>
      );
      break;
    case 'Secret':
      specific = [[t('col.type'), <code key="t">{s.type}</code>]];
      extra = <SecretValues data={data} kindKey={kindKey} />;
      break;
    case 'Job':
      specific = [[t('col.completions'), s.completions], [t('col.active'), s.active], ['Failed', s.failed], [t('col.images'), (s.images as string[]).join(', ')]];
      break;
    case 'CronJob':
      specific = [
        [t('detail.schedule'), <span key="s"><code>{s.schedule}</code> <span className="small muted">{t('detail.nextRunHint')}</span></span>],
        [t('col.suspended'), s.suspend ? t('common:yes') : t('common:no')], [t('col.active'), s.active],
        [t('col.lastSchedule'), formatDate(s.lastScheduleTime)], ['Last success', formatDate(s.lastSuccessfulTime)],
      ];
      break;
    case 'Namespace':
      specific = [[t('common:status'), s.status]];
      break;
    case 'PodDisruptionBudget':
      specific = [['minAvailable', String(s.minAvailable ?? '—')], ['maxUnavailable', String(s.maxUnavailable ?? '—')], [t('col.disruptions'), s.disruptionsAllowed], [t('detail.selector'), <Labels key="s" labels={s.selector} />]];
      break;
    case 'HorizontalPodAutoscaler':
      specific = [[t('col.target'), s.target], [t('col.min'), s.minReplicas], [t('col.max'), s.maxReplicas], [t('col.current'), s.currentReplicas ?? '—']];
      break;
  }

  return (
    <div className="stack" style={{ gap: 14 }}>
      {sentence}
      <div className="grid cols-2">
        <Card title={t('detail.properties')}>
          <KeyValue items={[...common, ...specific]} />
        </Card>
        <Card title={t('detail.whatIsIt')}>
          <p>{t(`kinds.${kind}.simple`, { defaultValue: '' })}</p>
          <details>
            <summary>{t('detail.technical')}</summary>
            <p className="small">{t(`kinds.${kind}.technical`, { defaultValue: '' })}</p>
          </details>
          <div style={{ marginTop: 10 }}>
            <div className="small muted">{t('detail.labels')}</div>
            <Labels labels={meta.labels} />
          </div>
        </Card>
      </div>
      {extra}
      <Conditions obj={o} />
    </div>
  );
}
