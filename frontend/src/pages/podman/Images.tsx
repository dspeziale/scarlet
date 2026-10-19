import { useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Download, Trash2, Wand2 } from 'lucide-react';
import { api, del } from '@/api/client';
import { useAction, useApi } from '@/hooks/api';
import { useAuth } from '@/auth/AuthContext';
import { DataTable, type Column } from '@/components/DataTable';
import { ConfirmDialog, Dialog } from '@/components/Dialog';
import { ErrorPanel } from '@/components/ErrorPanel';
import { Badge, Card, Field, Loading, PageHeader } from '@/components/ui';
import { formatAge, formatBytes } from '@/utils/format';
import { RuntimeCard, type PodmanInfo } from './common';

interface PodmanImage {
  id: string;
  fullId: string;
  tags: string[];
  size: number | null;
  created: number | string | null;
  containers: number;
  dangling: boolean;
  digest?: string | null;
}

function PullDialog({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation('podman');
  const [ref, setRef] = useState('');
  const [error, setError] = useState<unknown>(null);
  // Pulling large images can take minutes: allow up to the backend limit (600 s).
  const pull = useAction((reference: string) => api('/podman/images/pull', { method: 'POST', body: { reference }, timeoutMs: 620_000 }), {
    success: t('pullDone', { ref }),
    onSuccess: onClose,
  });
  return (
    <Dialog
      title={t('pullTitle')}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose} disabled={pull.busy}>
            {t('common:cancel')}
          </button>
          <button
            type="button"
            className="btn primary"
            disabled={!ref.trim() || pull.busy}
            onClick={() => {
              setError(null);
              pull.run(ref.trim()).catch((e) => setError(e));
            }}
          >
            {pull.busy && <span className="spinner" aria-hidden="true" />} {t('pull')}
          </button>
        </>
      }
    >
      <Field label={t('reference')} htmlFor="pull-ref" hint={t('referenceHint')}>
        <input id="pull-ref" className="input" value={ref} onChange={(e) => setRef(e.target.value)} placeholder="docker.io/library/nginx:1.27" data-autofocus spellCheck={false} />
      </Field>
      {pull.busy && <p className="small muted" aria-live="polite">{t('pulling')}</p>}
      {error ? <ErrorPanel error={error} /> : null}
    </Dialog>
  );
}

export default function Images() {
  const { t } = useTranslation('podman');
  const { can } = useAuth();
  const [params] = useSearchParams();
  const info = useApi<PodmanInfo>('/podman/info');
  const list = useApi<{ items: PodmanImage[] }>('/podman/images', undefined, { enabled: !!info.data?.connected });
  const [pullOpen, setPullOpen] = useState(false);
  const [removing, setRemoving] = useState<PodmanImage | null>(null);
  const [force, setForce] = useState(false);
  const [removeError, setRemoveError] = useState<unknown>(null);
  const remove = useAction(({ img, typed }: { img: PodmanImage; typed: string }) => del(`/podman/images/${encodeURIComponent(img.id)}`, { confirm: typed, force: force || undefined }), {
    success: t('removed'),
    onSuccess: () => setRemoving(null),
  });

  const columns: Column<PodmanImage>[] = [
    {
      id: 'tags',
      header: t('tags'),
      value: (r) => r.tags.join(' ') || r.id,
      cell: (r) => (r.tags.length ? r.tags.map((tg) => <span key={tg} className="chip" title={tg}>{tg}</span>) : <span className="muted">&lt;none&gt;</span>),
    },
    { id: 'id', header: t('id'), value: (r) => r.id, cell: (r) => <code>{r.id}</code> },
    { id: 'size', header: t('size'), numeric: true, value: (r) => r.size ?? 0, cell: (r) => formatBytes(r.size) },
    { id: 'containers', header: t('usedBy'), numeric: true, value: (r) => r.containers, cell: (r) => r.containers },
    {
      id: 'dangling',
      header: t('common:status'),
      value: (r) => (r.dangling ? 1 : 0),
      cell: (r) => (r.dangling ? <Badge tone="warn" title={t('danglingHelp')}>{t('dangling')}</Badge> : <Badge tone="ok">{t('tagged')}</Badge>),
    },
    { id: 'created', header: t('common:created'), value: (r) => Number(r.created ?? 0), cell: (r) => formatAge(r.created) },
    {
      id: 'actions',
      header: <span className="sr-only">{t('common:actions')}</span>,
      cell: (r) => (
        <div className="row" style={{ flexWrap: 'nowrap' }}>
          {r.tags[0] && can('workloads.deploy') && (
            <Link className="btn sm" to={`/operations/onboarding?image=${encodeURIComponent(r.tags[0])}`} title={t('onboardingHelp')}>
              <Wand2 size={14} /> {t('onboarding')}
            </Link>
          )}
          {can('podman.manage') && (
            <button
              type="button"
              className="btn sm icon"
              aria-label={`${t('action.remove')} ${r.tags[0] ?? r.id}`}
              title={t('action.remove')}
              onClick={() => {
                setForce(false);
                setRemoveError(null);
                setRemoving(r);
              }}
            >
              <Trash2 size={14} />
            </button>
          )}
        </div>
      ),
    },
  ];

  return (
    <>
      <PageHeader
        title={t('imagesTitle')}
        subtitle={t('imagesSubtitle')}
        actions={
          can('podman.manage') && info.data?.connected ? (
            <button type="button" className="btn primary" onClick={() => setPullOpen(true)}>
              <Download size={14} /> {t('pull')}
            </button>
          ) : undefined
        }
      />
      <div className="section">
        <RuntimeCard />
      </div>
      {info.data?.connected && (
        <Card title={t('imagesTitle')} flush>
          {list.isLoading && <Loading />}
          {list.error && <div style={{ padding: 12 }}><ErrorPanel error={list.error} onRetry={() => void list.refetch()} /></div>}
          {list.data && (
            <DataTable
              rows={list.data.items}
              columns={columns}
              rowKey={(r) => r.fullId ?? r.id}
              initialFilter={params.get('q') ?? ''}
              initialSort={{ id: 'tags', dir: 'asc' }}
              emptyText={t('noImages')}
              caption={t('imagesTitle')}
            />
          )}
        </Card>
      )}
      {pullOpen && <PullDialog onClose={() => setPullOpen(false)} />}
      {removing && (
        <ConfirmDialog
          spec={{
            title: t('removeImageTitle'),
            operation: t('action.remove'),
            resource: removing.tags[0] ?? removing.id,
            consequences: t('removeImageConsequences', { returnObjects: true, count: removing.containers }) as string[],
            risk: 'medium',
            typeToConfirm: removing.id,
            confirmLabel: t('action.remove'),
            danger: true,
            extra:
              removing.containers > 0 ? (
                <label className="checkbox" style={{ marginTop: 12 }}>
                  <input type="checkbox" checked={force} onChange={(e) => setForce(e.target.checked)} />
                  {t('forceImage')}
                </label>
              ) : undefined,
          }}
          busy={remove.busy}
          onClose={() => setRemoving(null)}
          error={removeError ? <div style={{ marginTop: 12 }}><ErrorPanel error={removeError} /></div> : null}
          onConfirm={(typed) => {
            setRemoveError(null);
            remove.run({ img: removing, typed }).catch((e) => setRemoveError(e));
          }}
        />
      )}
    </>
  );
}
