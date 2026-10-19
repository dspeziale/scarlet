import { useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Container as ContainerIcon } from 'lucide-react';
import { ApiError, del, post } from '@/api/client';
import { useAction, useApi } from '@/hooks/api';
import { ConfirmDialog, type ConfirmSpec } from '@/components/Dialog';
import { ErrorPanel } from '@/components/ErrorPanel';
import { Badge, Card, KeyValue, Loading, type Tone } from '@/components/ui';
import { formatBytes } from '@/utils/format';

export interface PodmanInfo {
  connected: boolean;
  configured?: boolean;
  endpoint?: string | null;
  version?: string;
  apiVersion?: string;
  os?: string;
  arch?: string;
  hostname?: string;
  kernel?: string;
  distribution?: { distribution?: string; version?: string } | null;
  rootless?: boolean;
  selinux?: boolean;
  cgroupVersion?: string;
  ociRuntime?: string;
  storageDriver?: string;
  graphRoot?: string;
  containers?: { number?: number; running?: number; stopped?: number; paused?: number };
  images?: number;
  registries?: { search?: string[]; configured?: Record<string, unknown> };
  cpus?: number;
  memTotal?: number;
  memFree?: number;
  uptime?: string;
  demo?: boolean;
  error?: { code: string; message: string; details?: string | null; params?: Record<string, unknown> };
}

export interface PodmanContainer {
  id: string;
  fullId: string;
  name: string;
  image: string;
  imageId: string;
  state: string;
  status: string;
  exitCode: number | null;
  created: string | null;
  startedAt: string | null;
  ports: string[];
  pod: string | null;
  labels: Record<string, string>;
  command: string;
  isInfra: boolean;
}

export interface PodmanStat {
  id: string;
  name: string;
  cpuPercent: number | null;
  memUsage: number | null;
  memLimit: number | null;
  memPercent: number | null;
  netInput: number | null;
  netOutput: number | null;
  pids: number | null;
}

export function stateTone(state: string, exitCode?: number | null): Tone {
  switch (state) {
    case 'running':
      return 'ok';
    case 'paused':
      return 'warn';
    case 'created':
    case 'configured':
      return 'info';
    case 'exited':
    case 'stopped':
      return exitCode ? 'err' : 'muted';
    case 'dead':
      return 'err';
    default:
      return 'muted';
  }
}

export function StateBadge({ state, exitCode }: { state: string; exitCode?: number | null }) {
  const { t } = useTranslation('podman');
  return (
    <Badge tone={stateTone(state, exitCode)} dot>
      {t(`state.${state}`, { defaultValue: state })}
      {state === 'exited' && exitCode ? ` (${exitCode})` : ''}
    </Badge>
  );
}

/** Header card stating clearly that this section manages the Podman runtime of this host, not Kubernetes. */
export function RuntimeCard() {
  const { t } = useTranslation('podman');
  const info = useApi<PodmanInfo>('/podman/info', undefined, { refetchInterval: 60_000 });
  if (info.isLoading) return <Loading />;
  if (info.error) return <ErrorPanel error={info.error} onRetry={() => void info.refetch()} />;
  const d = info.data!;
  return (
    <Card
      title={
        <span className="row">
          <ContainerIcon size={16} aria-hidden="true" /> {t('runtime.title')}
        </span>
      }
    >
      <p className="small muted">{t('runtime.notKubernetes')}</p>
      {!d.connected ? (
        <ErrorPanel
          error={
            new ApiError(503, {
              code: d.error?.code ?? 'podman_unavailable',
              message: d.error?.message ?? '',
              params: d.error?.params ?? {},
              details: d.error?.details,
            })
          }
          onRetry={() => void info.refetch()}
        />
      ) : (
        <div className="grid cols-2">
          <KeyValue
            items={[
              [t('runtime.runtime'), 'Podman'],
              [t('runtime.connection'), <Badge key="c" tone="ok" dot>{t('runtime.healthy')}</Badge>],
              [t('runtime.version'), d.version],
              [t('runtime.apiVersion'), d.apiVersion],
              [t('runtime.mode'), d.rootless ? t('runtime.rootless') : t('runtime.rootful')],
              [t('runtime.endpoint'), <code key="e">{d.endpoint}</code>],
            ]}
          />
          <KeyValue
            items={[
              [t('runtime.host'), `${d.hostname ?? '—'} (${d.distribution?.distribution ?? ''} ${d.distribution?.version ?? ''})`],
              [t('runtime.ociRuntime'), d.ociRuntime],
              [t('runtime.storage'), `${d.storageDriver ?? '—'} · ${d.graphRoot ?? ''}`],
              [t('runtime.cgroup'), d.cgroupVersion],
              [
                t('runtime.containers'),
                t('runtime.containersCount', { total: d.containers?.number ?? 0, running: d.containers?.running ?? 0, stopped: d.containers?.stopped ?? 0 }),
              ],
              [t('runtime.memory'), d.memTotal ? `${formatBytes(d.memFree)} / ${formatBytes(d.memTotal)} ${t('runtime.free')}` : '—'],
            ]}
          />
        </div>
      )}
    </Card>
  );
}

type ContainerOp = 'start' | 'stop' | 'restart' | 'remove';

/** Container operations with explicit confirmation of stop/restart/remove. */
export function useContainerOps(onDone?: (op: ContainerOp) => void): { open: (op: ContainerOp, c: { id: string; name: string; state: string }) => void; dialog: ReactNode } {
  const { t } = useTranslation('podman');
  const [state, setState] = useState<{ op: ContainerOp; c: { id: string; name: string; state: string } } | null>(null);
  const [force, setForce] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const action = useAction(
    async ({ op, c, typed }: { op: ContainerOp; c: { id: string; name: string }; typed: string }) => {
      if (op === 'remove') return del(`/podman/containers/${encodeURIComponent(c.id)}`, { confirm: typed, force: force || undefined });
      return post(`/podman/containers/${encodeURIComponent(c.id)}/action`, { action: op, confirm: typed || undefined });
    },
    {
      success: () => t(`done.${state?.op}`, { name: state?.c.name }),
      onSuccess: () => {
        const op = state?.op;
        setState(null);
        if (op) onDone?.(op);
      },
    },
  );
  const open = (op: ContainerOp, c: { id: string; name: string; state: string }) => {
    setError(null);
    setForce(false);
    if (op === 'start') {
      void action.run({ op, c, typed: '' }).catch(() => undefined);
      return;
    }
    setState({ op, c });
  };
  let dialog: ReactNode = null;
  if (state) {
    const { op, c } = state;
    const spec: ConfirmSpec = {
      title: t(`confirm.${op}.title`, { name: c.name }),
      operation: t(`action.${op}`),
      resource: `${t('container')}/${c.name}`,
      consequences: t(`confirm.${op}.consequences`, { returnObjects: true }) as string[],
      risk: op === 'remove' ? 'high' : 'medium',
      typeToConfirm: op === 'restart' ? undefined : c.name,
      confirmLabel: t(`action.${op}`),
      danger: op !== 'restart',
      extra:
        op === 'remove' && c.state === 'running' ? (
          <label className="checkbox" style={{ marginTop: 12 }}>
            <input type="checkbox" checked={force} onChange={(e) => setForce(e.target.checked)} />
            {t('confirm.remove.force')}
          </label>
        ) : undefined,
    };
    dialog = (
      <ConfirmDialog
        spec={spec}
        busy={action.busy}
        onClose={() => setState(null)}
        error={error ? <div style={{ marginTop: 12 }}><ErrorPanel error={error} /></div> : null}
        onConfirm={(typed) => {
          setError(null);
          action.run({ op, c, typed }).catch((e) => setError(e));
        }}
      />
    );
  }
  return { open, dialog };
}
