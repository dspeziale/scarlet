import { useMemo } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Play, RotateCw, Square, Trash2 } from 'lucide-react';
import { useApi } from '@/hooks/api';
import { useAuth } from '@/auth/AuthContext';
import { DataTable, type Column } from '@/components/DataTable';
import { ErrorPanel } from '@/components/ErrorPanel';
import { HelpLink } from '@/components/HelpLink';
import { Card, Loading, PageHeader } from '@/components/ui';
import { formatAge, formatBytes } from '@/utils/format';
import { RuntimeCard, StateBadge, useContainerOps, type PodmanContainer, type PodmanInfo, type PodmanStat } from './common';

export default function Containers() {
  const { t } = useTranslation('podman');
  const { can } = useAuth();
  const navigate = useNavigate();
  const info = useApi<PodmanInfo>('/podman/info');
  const list = useApi<{ items: PodmanContainer[] }>('/podman/containers', { all: true }, { enabled: !!info.data?.connected });
  const stats = useApi<{ items: PodmanStat[] }>('/podman/stats', undefined, { enabled: !!info.data?.connected, refetchInterval: 30_000 });
  const ops = useContainerOps();
  const statById = useMemo(() => new Map((stats.data?.items ?? []).map((s) => [s.id, s])), [stats.data]);
  const canOperate = can('podman.operate');
  const canManage = can('podman.manage');

  const columns: Column<PodmanContainer>[] = [
    {
      id: 'name',
      header: t('common:name'),
      value: (r) => r.name,
      cell: (r) => (
        <Link to={`/podman/containers/${encodeURIComponent(r.id)}`}>
          <strong>{r.name}</strong>
        </Link>
      ),
    },
    { id: 'state', header: t('common:status'), value: (r) => r.state, cell: (r) => <StateBadge state={r.state} exitCode={r.exitCode} /> },
    { id: 'image', header: t('image'), value: (r) => r.image, cell: (r) => <span className="chip" title={r.image}>{r.image}</span> },
    { id: 'ports', header: t('ports'), value: (r) => r.ports.join(' '), cell: (r) => (r.ports.length ? r.ports.map((p) => <span key={p} className="chip">{p}</span>) : '—') },
    {
      id: 'cpu',
      header: 'CPU',
      numeric: true,
      value: (r) => statById.get(r.id)?.cpuPercent ?? null,
      cell: (r) => {
        const s = statById.get(r.id);
        return s?.cpuPercent != null ? `${s.cpuPercent.toFixed(1)}%` : '—';
      },
    },
    {
      id: 'mem',
      header: t('memory'),
      numeric: true,
      value: (r) => statById.get(r.id)?.memUsage ?? null,
      cell: (r) => {
        const s = statById.get(r.id);
        return s?.memUsage != null ? formatBytes(s.memUsage) : '—';
      },
    },
    { id: 'created', header: t('common:age'), value: (r) => r.created ?? '', cell: (r) => <span title={r.created ?? ''}>{formatAge(r.created)}</span> },
    {
      id: 'actions',
      header: <span className="sr-only">{t('common:actions')}</span>,
      cell: (r) => (
        <div className="row" style={{ flexWrap: 'nowrap' }}>
          {r.state === 'running' ? (
            <>
              <button
                type="button"
                className="btn sm icon"
                disabled={!canOperate}
                title={canOperate ? t('action.restart') : t('common:permissionDenied')}
                aria-label={`${t('action.restart')} ${r.name}`}
                onClick={() => ops.open('restart', r)}
              >
                <RotateCw size={14} />
              </button>
              <button
                type="button"
                className="btn sm icon"
                disabled={!canOperate}
                title={canOperate ? t('action.stop') : t('common:permissionDenied')}
                aria-label={`${t('action.stop')} ${r.name}`}
                onClick={() => ops.open('stop', r)}
              >
                <Square size={14} />
              </button>
            </>
          ) : (
            <button
              type="button"
              className="btn sm icon"
              disabled={!canOperate}
              title={canOperate ? t('action.start') : t('common:permissionDenied')}
              aria-label={`${t('action.start')} ${r.name}`}
              onClick={() => ops.open('start', r)}
            >
              <Play size={14} />
            </button>
          )}
          {canManage && (
            <button type="button" className="btn sm icon" title={t('action.remove')} aria-label={`${t('action.remove')} ${r.name}`} onClick={() => ops.open('remove', r)}>
              <Trash2 size={14} />
            </button>
          )}
        </div>
      ),
    },
  ];

  return (
    <>
      <PageHeader title={t('containersTitle')} subtitle={t('containersSubtitle')} help={<HelpLink slug="cos-e-podman" />} />
      <div className="section">
        <RuntimeCard />
      </div>
      {info.data?.connected && (
        <Card title={t('containersTitle')} flush>
          {list.isLoading && <Loading />}
          {list.error && <div style={{ padding: 12 }}><ErrorPanel error={list.error} onRetry={() => void list.refetch()} /></div>}
          {list.data && (
            <DataTable
              rows={list.data.items.filter((c) => !c.isInfra)}
              columns={columns}
              rowKey={(r) => r.fullId ?? r.id}
              onRowClick={(r) => navigate(`/podman/containers/${encodeURIComponent(r.id)}`)}
              initialSort={{ id: 'name', dir: 'asc' }}
              emptyText={t('noContainers')}
              caption={t('containersTitle')}
            />
          )}
          {stats.error && <p className="small muted" style={{ padding: '0 12px 12px' }}>{t('statsUnavailable')}</p>}
        </Card>
      )}
      {ops.dialog}
    </>
  );
}
