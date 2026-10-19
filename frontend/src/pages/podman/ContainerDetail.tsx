import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Play, RotateCw, Square, Trash2 } from 'lucide-react';
import { useApi } from '@/hooks/api';
import { useAuth } from '@/auth/AuthContext';
import { ErrorPanel } from '@/components/ErrorPanel';
import { LogViewer } from '@/components/LogViewer';
import { Card, KeyValue, Loading, PageHeader, Segmented, TabPanel, Tabs } from '@/components/ui';
import { formatDate } from '@/utils/format';
import { StateBadge, useContainerOps } from './common';

type Inspect = Record<string, unknown> & {
  Id?: string;
  Name?: string;
  ImageName?: string;
  Image?: string;
  Created?: string;
  State?: { Status?: string; Running?: boolean; ExitCode?: number; StartedAt?: string; FinishedAt?: string; Error?: string; OOMKilled?: boolean };
  Config?: { Env?: string[]; Cmd?: string[]; Entrypoint?: string[] | string; Labels?: Record<string, string>; WorkingDir?: string; User?: string; Tty?: boolean };
  HostConfig?: { RestartPolicy?: { Name?: string } };
  NetworkSettings?: { Ports?: Record<string, { HostIp?: string; HostPort?: string }[] | null> };
  Mounts?: { Source?: string; Destination?: string; Type?: string; RW?: boolean }[];
  RestartCount?: number;
};

export default function ContainerDetail() {
  const { t } = useTranslation('podman');
  const { id = '' } = useParams();
  const { can } = useAuth();
  const navigate = useNavigate();
  const [tab, setTab] = useState('overview');
  const [view, setView] = useState<'simple' | 'json'>('simple');
  const q = useApi<{ inspect: Inspect }>(`/podman/containers/${encodeURIComponent(id)}`);
  const ops = useContainerOps((op) => {
    if (op === 'remove') navigate('/podman/containers');
  });

  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorPanel error={q.error} onRetry={() => void q.refetch()} />;
  const d = q.data!.inspect;
  const name = (d.Name ?? id).replace(/^\//, '');
  const state = d.State?.Status ?? 'unknown';
  const ref = { id, name, state };
  const ports = Object.entries(d.NetworkSettings?.Ports ?? {}).flatMap(([cport, binds]) =>
    binds && binds.length ? binds.map((b) => `${b.HostIp || '0.0.0.0'}:${b.HostPort} → ${cport}`) : [cport],
  );
  const entry = Array.isArray(d.Config?.Entrypoint) ? d.Config?.Entrypoint.join(' ') : d.Config?.Entrypoint;

  return (
    <>
      <PageHeader
        breadcrumbs={
          <>
            <Link to="/podman/containers">{t('containersTitle')}</Link> / {name}
          </>
        }
        title={
          <>
            {name} <StateBadge state={state} exitCode={d.State?.ExitCode} />
          </>
        }
        subtitle={t('detailSubtitle')}
        actions={
          <>
            {state === 'running' ? (
              <>
                <button type="button" className="btn" disabled={!can('podman.operate')} title={can('podman.operate') ? undefined : t('common:permissionDenied')} onClick={() => ops.open('restart', ref)}>
                  <RotateCw size={14} /> {t('action.restart')}
                </button>
                <button type="button" className="btn" disabled={!can('podman.operate')} title={can('podman.operate') ? undefined : t('common:permissionDenied')} onClick={() => ops.open('stop', ref)}>
                  <Square size={14} /> {t('action.stop')}
                </button>
              </>
            ) : (
              <button type="button" className="btn primary" disabled={!can('podman.operate')} title={can('podman.operate') ? undefined : t('common:permissionDenied')} onClick={() => ops.open('start', ref)}>
                <Play size={14} /> {t('action.start')}
              </button>
            )}
            {can('podman.manage') && (
              <button type="button" className="btn danger" onClick={() => ops.open('remove', ref)}>
                <Trash2 size={14} /> {t('action.remove')}
              </button>
            )}
          </>
        }
      />
      <Tabs
        label={t('detailTabs')}
        value={tab}
        onChange={setTab}
        tabs={[
          { id: 'overview', label: t('tabs.overview') },
          { id: 'logs', label: t('tabs.logs'), hidden: !can('logs.read') },
        ]}
      />
      {tab === 'overview' && (
        <TabPanel id="overview">
          <div className="row" style={{ marginBottom: 12 }}>
            <Segmented
              label={t('viewMode')}
              value={view}
              onChange={setView}
              options={[
                { value: 'simple', label: t('common:simpleView') },
                { value: 'json', label: 'JSON' },
              ]}
            />
          </div>
          {view === 'simple' ? (
            <div className="grid cols-2">
              <Card title={t('summary')}>
                <KeyValue
                  items={[
                    [t('id'), <code key="id">{(d.Id ?? '').slice(0, 12)}</code>],
                    [t('image'), <code key="img">{d.ImageName ?? d.Image}</code>],
                    [t('common:status'), <StateBadge key="st" state={state} exitCode={d.State?.ExitCode} />],
                    [t('exitCode'), d.State?.ExitCode ?? '—'],
                    [t('oomKilled'), d.State?.OOMKilled ? t('common:yes') : t('common:no')],
                    [t('startedAt'), formatDate(d.State?.StartedAt)],
                    [t('common:created'), formatDate(d.Created)],
                    [t('restartPolicy'), d.HostConfig?.RestartPolicy?.Name || 'no'],
                    [t('restartCount'), d.RestartCount ?? '—'],
                  ]}
                />
                {d.State?.Error && <p className="small" style={{ color: 'var(--err)' }}>{d.State.Error}</p>}
              </Card>
              <Card title={t('config')}>
                <KeyValue
                  items={[
                    [t('entrypoint'), entry ? <code key="e">{entry}</code> : '—'],
                    [t('command'), d.Config?.Cmd?.length ? <code key="c">{d.Config.Cmd.join(' ')}</code> : '—'],
                    [t('user'), d.Config?.User || 'root'],
                    [t('workingDir'), d.Config?.WorkingDir || '—'],
                    [t('ports'), ports.length ? ports.map((p) => <span key={p} className="chip">{p}</span>) : '—'],
                    [
                      t('mounts'),
                      d.Mounts?.length
                        ? d.Mounts.map((m) => (
                            <div key={`${m.Source}-${m.Destination}`} className="small">
                              <code>{m.Source}</code> → <code>{m.Destination}</code> {m.RW === false ? '(ro)' : ''}
                            </div>
                          ))
                        : '—',
                    ],
                  ]}
                />
              </Card>
              <Card title={t('env')}>
                <p className="small muted">{t('envMasked')}</p>
                {(d.Config?.Env ?? []).map((e) => (
                  <div key={e} className="chip" style={{ display: 'block', maxWidth: '100%' }} title={e}>
                    {e}
                  </div>
                ))}
              </Card>
              <Card title={t('common:labels')}>
                {Object.keys(d.Config?.Labels ?? {}).length === 0
                  ? '—'
                  : Object.entries(d.Config?.Labels ?? {}).map(([k, v]) => (
                      <span key={k} className="chip" title={`${k}=${v}`}>
                        {k}={v}
                      </span>
                    ))}
              </Card>
            </div>
          ) : (
            <pre className="code" aria-label="JSON">{JSON.stringify(d, null, 2)}</pre>
          )}
        </TabPanel>
      )}
      {tab === 'logs' && (
        <TabPanel id="logs">
          <p className="small muted">{t('logsNoLive')}</p>
          <LogViewer source={{ path: `/podman/containers/${encodeURIComponent(id)}/logs` }} />
        </TabPanel>
      )}
      {ops.dialog}
    </>
  );
}
