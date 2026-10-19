import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Copy, Download, PlayCircle, ShieldCheck, Trash2 } from 'lucide-react';
import { del, downloadUrl, post } from '@/api/client';
import type { Check } from '@/api/types';
import { useAuth } from '@/auth/AuthContext';
import { useAction, useApi, useOperation } from '@/hooks/api';
import { Alert, Badge, Card, Empty, KeyValue, Loading, PageHeader, StatCard } from '@/components/ui';
import { DataTable } from '@/components/DataTable';
import { ErrorPanel } from '@/components/ErrorPanel';
import { HelpLink } from '@/components/HelpLink';
import { ConfirmDialog, Dialog } from '@/components/Dialog';
import { CheckList } from '@/components/IssueCard';
import { formatAge, formatBytes, formatDate } from '@/utils/format';
import '@/styles/pages-b.css';

interface BackupRow {
  id: number | null;
  filename: string;
  created_at: string;
  size_bytes: number;
  sha256: string;
  status: 'running' | 'success' | 'failed' | 'deleted';
  trigger: string;
  created_by: string;
  includes: string[];
  verified_at: string | null;
  verify_result: string | null;
  detail: string;
  present: boolean;
}

interface BackupList {
  items: BackupRow[];
  directory: string;
  retentionCount: number;
  includeManifests: boolean;
}

interface VerifyResult {
  ok: boolean;
  sha256: string;
  checks: Check[];
}

const STATUS_TONE = { success: 'ok', failed: 'err', running: 'info', deleted: 'muted' } as const;

export default function Backup() {
  const { t } = useTranslation('operations');
  const { can } = useAuth();
  const list = useApi<BackupList>(can('backup.read') ? '/backups' : null);
  const [includeManifests, setIncludeManifests] = useState<boolean | null>(null);
  const [opId, setOpId] = useState<string | null>(null);
  const op = useOperation(opId);
  const [verify, setVerify] = useState<{ file: string; result: VerifyResult } | null>(null);
  const [toDelete, setToDelete] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [copied, setCopied] = useState<string | null>(null);

  const create = useAction((inc: boolean) => post<{ operation: { id: string } }>('/backups', { include_manifests: inc }), {
    onSuccess: (r) => setOpId(r.operation.id),
  });
  const verifyAction = useAction((f: string) => post<VerifyResult>(`/backups/${encodeURIComponent(f)}/verify`), {});
  const remove = useAction((f: string) => del(`/backups/${encodeURIComponent(f)}`, { confirm: f }), {
    success: t('backup.deleted'),
    onSuccess: () => setToDelete(null),
  });

  if (!can('backup.read')) {
    return (
      <>
        <PageHeader title={t('backup.title')} />
        <Alert tone="warn">{t('common:permissionDenied')}</Alert>
      </>
    );
  }

  const items = list.data?.items ?? [];
  const last = items.find((b) => b.status === 'success');
  const inc = includeManifests ?? list.data?.includeManifests ?? false;
  const file = selected ?? last?.filename ?? '<file>';
  const running = op.data?.status === 'running' || create.busy;

  const copy = (text: string) => {
    void navigator.clipboard?.writeText(text).then(() => {
      setCopied(text);
      setTimeout(() => setCopied(null), 2000);
    });
  };

  return (
    <>
      <PageHeader
        title={t('backup.title')}
        subtitle={t('backup.subtitle')}
        help={
          <div className="row">
            <HelpLink slug="backup" />
            <HelpLink slug="proc-backup" />
            <HelpLink slug="proc-restore" />
          </div>
        }
      />
      <div className="grid cols-2 section">
        <Alert tone="info" title={t('backup.whatTitle')}>
          <ul style={{ margin: 0, paddingLeft: 18 }}>
            <li>{t('backup.what1')}</li>
            <li>{t('backup.what2')}</li>
            <li>{t('backup.what3')}</li>
          </ul>
        </Alert>
        <Alert tone="warn" title={t('backup.notTitle')}>
          <ul style={{ margin: 0, paddingLeft: 18 }}>
            <li>{t('backup.not1')}</li>
            <li>{t('backup.not2')}</li>
            <li>{t('backup.not3')}</li>
          </ul>
        </Alert>
      </div>

      {list.isLoading && <Loading />}
      {list.error && <ErrorPanel error={list.error} onRetry={() => void list.refetch()} />}
      {list.data && (
        <>
          <div className="grid cols-4 section">
            <StatCard
              label={t('backup.last')}
              value={last ? formatAge(last.created_at) : '—'}
              sub={last ? formatDate(last.created_at) : t('backup.never')}
              tone={!last ? 'warn' : Date.now() - Date.parse(last.created_at) > 2 * 86400_000 ? 'warn' : 'ok'}
            />
            <StatCard label={t('backup.lastStatus')} value={items[0] ? <Badge tone={STATUS_TONE[items[0].status]}>{t(`backup.status.${items[0].status}`)}</Badge> : '—'} sub={items[0]?.filename} />
            <StatCard label={t('backup.size')} value={last ? formatBytes(last.size_bytes) : '—'} />
            <StatCard label={t('backup.retention')} value={list.data.retentionCount} sub={t('backup.retentionSub')} />
          </div>
          <Card title={t('backup.runTitle')}>
            <KeyValue items={[[t('backup.destination'), <code key="d">{list.data.directory}</code>]]} />
            {can('backup.manage') ? (
              <div className="row" style={{ marginTop: 10 }}>
                <label className="checkbox">
                  <input type="checkbox" checked={inc} onChange={(e) => setIncludeManifests(e.target.checked)} />
                  {t('backup.includeManifests')}
                </label>
                <button className="btn primary" disabled={running} onClick={() => void create.run(inc)}>
                  <PlayCircle size={16} /> {t('backup.runNow')}
                </button>
              </div>
            ) : (
              <p className="small muted">{t('backup.manageOnly')}</p>
            )}
            <p className="small muted">{t('backup.includeHint')}</p>
            {op.data && (
              <div aria-live="polite" style={{ marginTop: 10 }}>
                <Alert tone={op.data.status === 'succeeded' ? 'ok' : op.data.status === 'failed' ? 'err' : 'info'} title={t(`backup.op.${op.data.status}`)}>
                  <ul className="step-log">
                    {op.data.steps.map((s, i) => (
                      <li key={i}>
                        {formatDate(s.ts)} · {t(`backup.step.${s.step}`, { defaultValue: s.step })}
                        {typeof s.objects === 'number' ? ` (${s.objects})` : ''}
                      </li>
                    ))}
                  </ul>
                  {op.data.error && <p className="small">{op.data.error.message}</p>}
                </Alert>
              </div>
            )}
          </Card>
          <div className="section" style={{ marginTop: 14 }}>
            <Card title={t('backup.history')} flush>
              {items.length === 0 ? (
                <Empty>{t('backup.none')}</Empty>
              ) : (
                <DataTable
                  rows={items}
                  rowKey={(r) => r.filename}
                  caption={t('backup.history')}
                  onRowClick={(r) => setSelected(r.filename)}
                  columns={[
                    { id: 'file', header: t('backup.file'), cell: (r) => <code className={r.filename === selected ? 'sel-row' : undefined}>{r.filename}</code>, value: (r) => r.filename },
                    { id: 'created', header: t('common:created'), cell: (r) => formatDate(r.created_at), value: (r) => r.created_at },
                    { id: 'trigger', header: t('backup.trigger'), cell: (r) => t(`backup.triggers.${r.trigger}`, { defaultValue: r.trigger }), value: (r) => r.trigger },
                    { id: 'status', header: t('common:status'), cell: (r) => <Badge tone={STATUS_TONE[r.status]}>{t(`backup.status.${r.status}`)}</Badge>, value: (r) => r.status },
                    { id: 'size', header: t('backup.size'), cell: (r) => formatBytes(r.size_bytes), value: (r) => r.size_bytes, numeric: true },
                    {
                      id: 'sha',
                      header: 'SHA-256',
                      cell: (r) =>
                        r.sha256 ? (
                          <button className="btn ghost sm" title={r.sha256} onClick={() => copy(r.sha256)} aria-label={t('backup.copySha')}>
                            <code>{r.sha256.slice(0, 12)}…</code> <Copy size={12} /> {copied === r.sha256 ? t('common:copied') : ''}
                          </button>
                        ) : (
                          '—'
                        ),
                    },
                    { id: 'inc', header: t('backup.includes'), cell: (r) => r.includes.map((i) => <span key={i} className="chip">{t(`backup.inc.${i}`, { defaultValue: i })}</span>) },
                    {
                      id: 'ver',
                      header: t('backup.verified'),
                      cell: (r) => (r.verify_result ? <Badge tone={r.verify_result === 'ok' ? 'ok' : 'err'}>{r.verify_result === 'ok' ? t('backup.verifyOk') : t('backup.verifyFail')}</Badge> : '—'),
                    },
                    {
                      id: 'act',
                      header: <span className="sr-only">{t('common:actions')}</span>,
                      cell: (r) =>
                        r.present && r.status === 'success' ? (
                          <span className="row">
                            {can('backup.manage') && (
                              <button
                                className="btn sm"
                                disabled={verifyAction.busy}
                                onClick={() => void verifyAction.run(r.filename).then((res) => setVerify({ file: r.filename, result: res }))}
                              >
                                <ShieldCheck size={14} /> {t('backup.verify')}
                              </button>
                            )}
                            {can('backup.manage') && (
                              <button className="btn sm icon" aria-label={t('common:download')} title={t('common:download')} onClick={() => downloadUrl(`/backups/${encodeURIComponent(r.filename)}/download`)}>
                                <Download size={14} />
                              </button>
                            )}
                            {can('backup.manage') && (
                              <button className="btn sm icon" aria-label={t('common:delete')} title={t('common:delete')} onClick={() => setToDelete(r.filename)}>
                                <Trash2 size={14} />
                              </button>
                            )}
                          </span>
                        ) : r.detail ? (
                          <span className="small muted" title={r.detail}>{r.detail.slice(0, 60)}</span>
                        ) : null,
                    },
                  ]}
                />
              )}
            </Card>
          </div>
          <Card title={t('backup.restoreTitle')}>
            <p>{t('backup.restoreExplain')}</p>
            <ol>
              <li>
                {t('backup.restoreStep1')}
                <code className="cmd">sudo systemctl stop pkm</code>
              </li>
              <li>
                {t('backup.restoreStep2')}
                <code className="cmd">sudo /opt/pkm/current/scripts/restore.sh {list.data.directory.replace(/\/$/, '')}/{file}</code>
              </li>
              <li>
                {t('backup.restoreStep3')}
                <code className="cmd">sudo systemctl start pkm</code>
              </li>
            </ol>
            <p className="small muted">{t('backup.restoreSelected')}</p>
            <h3>{t('backup.scheduledTitle')}</h3>
            <p className="small">{t('backup.scheduledText')}</p>
            <code className="cmd">systemctl list-timers pkm-backup.timer{'\n'}journalctl -u pkm-backup</code>
          </Card>
        </>
      )}

      {verify && (
        <Dialog title={t('backup.verifyTitle', { file: verify.file })} onClose={() => setVerify(null)}>
          <Alert tone={verify.result.ok ? 'ok' : 'err'}>{verify.result.ok ? t('backup.verifyOkText') : t('backup.verifyFailText')}</Alert>
          <CheckList checks={verify.result.checks.map((c) => ({ ...c, params: c.params ?? {} }))} />
          <p className="small muted">
            SHA-256: <code>{verify.result.sha256}</code>
          </p>
        </Dialog>
      )}
      {toDelete && (
        <ConfirmDialog
          spec={{
            title: t('backup.deleteTitle'),
            operation: t('common:delete'),
            resource: toDelete,
            consequences: [t('backup.deleteCons')],
            risk: 'high',
            typeToConfirm: toDelete,
            danger: true,
          }}
          busy={remove.busy}
          onClose={() => setToDelete(null)}
          onConfirm={() => void remove.run(toDelete)}
        />
      )}
    </>
  );
}
