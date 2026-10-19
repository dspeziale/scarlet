import { useEffect, useMemo, useState, type FormEvent } from 'react';
import { Navigate, useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { RotateCcw, Save } from 'lucide-react';
import { del, put } from '@/api/client';
import { useAuth } from '@/auth/AuthContext';
import { useAction, useApi, useSystemStatus } from '@/hooks/api';
import { ConfirmDialog } from '@/components/Dialog';
import { ErrorPanel } from '@/components/ErrorPanel';
import { HelpLink } from '@/components/HelpLink';
import { Alert, Badge, Card, KeyValue, Loading, PageHeader } from '@/components/ui';

type Value = string | number | boolean | null | string[];
interface Entry {
  value: Value;
  source: 'file' | 'ui';
  editable: boolean;
}
export interface SettingsData {
  effective: Record<string, Record<string, Entry>>;
  editable: Record<string, string[]>;
  readonly: {
    mode: string;
    environment: string;
    configFile: string | null;
    server: { host: string; port: number; tls: boolean; tlsCert: string | null; trustedProxies: string[] };
    database: string;
    logFile: string | null;
    backupDirectory: string;
    cookieSecure: boolean;
  };
}

type FieldKind = 'bool' | 'int' | 'float' | 'text' | 'level';
interface FieldDef {
  key: string;
  kind: FieldKind;
  min?: number;
  max?: number;
}
interface Group {
  section: string; // backend section
  fields: FieldDef[];
}

/** Which backend sections/keys each settings page shows. */
export const PAGES: Record<string, { groups: Group[]; guide?: string }> = {
  kubernetes: {
    guide: 'proc-collegare-kubernetes',
    groups: [
      {
        section: 'kubernetes',
        fields: [
          { key: 'enabled', kind: 'bool' },
          { key: 'kubeconfig', kind: 'text' },
          { key: 'context', kind: 'text' },
          { key: 'in_cluster', kind: 'bool' },
          { key: 'request_timeout', kind: 'float', min: 1, max: 300 },
          { key: 'cache_ttl_seconds', kind: 'float', min: 0, max: 60 },
        ],
      },
      {
        section: 'monitoring',
        fields: [
          { key: 'metrics_server', kind: 'bool' },
          { key: 'prometheus_url', kind: 'text' },
          { key: 'prometheus_timeout', kind: 'float', min: 1, max: 120 },
          { key: 'prometheus_verify_tls', kind: 'bool' },
          { key: 'poll_interval_seconds', kind: 'int', min: 10, max: 3600 },
        ],
      },
    ],
  },
  podman: {
    guide: 'proc-collegare-podman',
    groups: [
      {
        section: 'podman',
        fields: [
          { key: 'enabled', kind: 'bool' },
          { key: 'url', kind: 'text' },
          { key: 'timeout', kind: 'float', min: 1, max: 300 },
        ],
      },
    ],
  },
  logging: {
    groups: [
      { section: 'logging', fields: [{ key: 'level', kind: 'level' }] },
      {
        section: 'logs',
        fields: [
          { key: 'max_tail_lines', kind: 'int', min: 100, max: 50000 },
          { key: 'stream_max_seconds', kind: 'int', min: 30, max: 86400 },
          { key: 'stream_max_lines', kind: 'int', min: 100, max: 1000000 },
        ],
      },
    ],
  },
  backup: {
    guide: 'proc-backup',
    groups: [
      {
        section: 'backup',
        fields: [
          { key: 'retention_count', kind: 'int', min: 1, max: 1000 },
          { key: 'include_manifests', kind: 'bool' },
        ],
      },
      { section: 'audit', fields: [{ key: 'retention_days', kind: 'int', min: 7, max: 3650 }] },
    ],
  },
  auth: {
    groups: [
      {
        section: 'auth',
        fields: [
          { key: 'session_idle_minutes', kind: 'int', min: 5, max: 1440 },
          { key: 'session_absolute_hours', kind: 'int', min: 1, max: 720 },
          { key: 'login_max_attempts', kind: 'int', min: 3, max: 50 },
          { key: 'lockout_minutes', kind: 'int', min: 1, max: 1440 },
          { key: 'password_min_length', kind: 'int', min: 8, max: 128 },
        ],
      },
    ],
  },
};

const SECTIONS = ['system', 'kubernetes', 'podman', 'logging', 'backup', 'auth'];

function toForm(v: Value): string | boolean {
  if (typeof v === 'boolean') return v;
  if (v === null || v === undefined) return '';
  return String(v);
}

function fromForm(kind: FieldKind, v: string | boolean): Value {
  if (kind === 'bool') return !!v;
  if (kind === 'int') return v === '' ? null : parseInt(String(v), 10);
  if (kind === 'float') return v === '' ? null : parseFloat(String(v));
  return String(v).trim() === '' ? null : String(v).trim();
}

function GroupForm({ group, data, readOnly }: { group: Group; data: SettingsData; readOnly: boolean }) {
  const { t } = useTranslation('settings');
  const entries = data.effective[group.section] ?? {};
  const initial = useMemo(() => Object.fromEntries(group.fields.map((f) => [f.key, toForm(entries[f.key]?.value ?? null)])), [entries, group.fields]);
  const [form, setForm] = useState<Record<string, string | boolean>>(initial);
  const [error, setError] = useState<unknown>(null);
  const [confirmReset, setConfirmReset] = useState(false);
  useEffect(() => setForm(initial), [initial]);

  const changed = group.fields.filter((f) => form[f.key] !== initial[f.key]);
  const save = useAction(
    () => put(`/settings/${group.section}`, Object.fromEntries(changed.map((f) => [f.key, fromForm(f.kind, form[f.key])]))),
    { success: t('saved') },
  );
  const reset = useAction(() => del(`/settings/${group.section}`), { success: t('resetDone'), onSuccess: () => setConfirmReset(false) });
  const hasUi = group.fields.some((f) => entries[f.key]?.source === 'ui');

  const submit = (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!changed.length) return;
    save.run().catch((err) => setError(err));
  };

  return (
    <Card
      title={t(`group.${group.section}`)}
      actions={
        !readOnly && hasUi ? (
          <button type="button" className="btn sm" onClick={() => setConfirmReset(true)}>
            <RotateCcw size={14} /> {t('resetFile')}
          </button>
        ) : undefined
      }
    >
      <p className="small muted">{t(`groupHelp.${group.section}`)}</p>
      <form onSubmit={submit} aria-label={t(`group.${group.section}`)}>
        {group.fields.map((f) => {
          const id = `set-${group.section}-${f.key}`;
          const entry = entries[f.key];
          const label = (
            <span className="row" style={{ gap: 6 }}>
              {t(`field.${group.section}.${f.key}.label`)}
              {entry && (
                <Badge tone={entry.source === 'ui' ? 'info' : 'muted'} title={t(`sourceHelp.${entry.source}`)}>
                  {t(`source.${entry.source}`)}
                </Badge>
              )}
            </span>
          );
          const hint = t(`field.${group.section}.${f.key}.hint`, { defaultValue: '' });
          if (f.kind === 'bool') {
            return (
              <div className="field" key={f.key}>
                <label className="checkbox" htmlFor={id}>
                  <input id={id} type="checkbox" checked={!!form[f.key]} disabled={readOnly} onChange={(e) => setForm({ ...form, [f.key]: e.target.checked })} />
                  {label}
                </label>
                {hint && <div className="hint">{hint}</div>}
              </div>
            );
          }
          return (
            <div className="field" key={f.key}>
              <label htmlFor={id}>{label}</label>
              {f.kind === 'level' ? (
                <select id={id} className="input" value={String(form[f.key])} disabled={readOnly} onChange={(e) => setForm({ ...form, [f.key]: e.target.value })}>
                  {['DEBUG', 'INFO', 'WARNING', 'ERROR'].map((l) => (
                    <option key={l}>{l}</option>
                  ))}
                </select>
              ) : (
                <input
                  id={id}
                  className="input"
                  type={f.kind === 'text' ? 'text' : 'number'}
                  step={f.kind === 'float' ? 'any' : 1}
                  min={f.min}
                  max={f.max}
                  value={String(form[f.key])}
                  disabled={readOnly}
                  spellCheck={false}
                  onChange={(e) => setForm({ ...form, [f.key]: e.target.value })}
                />
              )}
              {hint && <div className="hint">{hint}</div>}
            </div>
          );
        })}
        {error ? <ErrorPanel error={error} /> : null}
        {!readOnly && (
          <div className="row">
            <button type="submit" className="btn primary" disabled={!changed.length || save.busy}>
              {save.busy ? <span className="spinner" aria-hidden="true" /> : <Save size={14} />} {t('save', { count: changed.length })}
            </button>
            {changed.length > 0 && (
              <button type="button" className="btn" onClick={() => setForm(initial)}>
                {t('discard')}
              </button>
            )}
          </div>
        )}
      </form>
      {confirmReset && (
        <ConfirmDialog
          spec={{
            title: t('resetTitle', { section: t(`group.${group.section}`) }),
            operation: t('resetFile'),
            resource: `settings/${group.section}`,
            consequences: [t('resetConsequence')],
            risk: 'low',
          }}
          busy={reset.busy}
          onClose={() => setConfirmReset(false)}
          onConfirm={() => void reset.run()}
        />
      )}
    </Card>
  );
}

function ConnectionStatus({ which }: { which: 'kubernetes' | 'podman' }) {
  const { t } = useTranslation('settings');
  const st = useSystemStatus();
  if (!st.data) return null;
  const s = which === 'kubernetes' ? st.data.kubernetes : st.data.podman;
  return (
    <div aria-live="polite">
      {s.connected ? (
        <Alert tone="ok" title={t('connected')}>
          {which === 'kubernetes'
            ? t('k8sConnected', { context: st.data.kubernetes.context, version: st.data.kubernetes.version, server: st.data.kubernetes.server })
            : t('podmanConnected', { version: st.data.podman.version, endpoint: st.data.podman.endpoint })}
        </Alert>
      ) : (
        <Alert tone="err" title={t('notConnected')}>
          <p>{s.error?.message}</p>
          {s.error?.details && <p className="small mono">{s.error.details}</p>}
        </Alert>
      )}
    </div>
  );
}

function SystemInfo({ data }: { data: SettingsData }) {
  const { t } = useTranslation('settings');
  const st = useSystemStatus();
  const r = data.readonly;
  return (
    <div className="grid cols-2">
      <Card title={t('system.app')}>
        <KeyValue
          items={[
            [t('system.mode'), <Badge key="m" tone={r.mode === 'demo' ? 'purple' : 'ok'}>{r.mode.toUpperCase()}</Badge>],
            [t('system.environment'), r.environment],
            [t('system.version'), st.data?.version],
            [t('system.apiVersion'), st.data?.apiVersion],
            [t('system.configFile'), r.configFile ? <code key="c">{r.configFile}</code> : t('system.noConfigFile')],
            [t('system.database'), <code key="d">{r.database}</code>],
            [t('system.logFile'), r.logFile ? <code key="l">{r.logFile}</code> : t('system.journalOnly')],
            [t('system.backupDir'), <code key="b">{r.backupDirectory}</code>],
          ]}
        />
      </Card>
      <Card title={t('system.server')}>
        <KeyValue
          items={[
            [t('system.bind'), <code key="h">{`${r.server.host}:${r.server.port}`}</code>],
            [t('system.tls'), r.server.tls ? <Badge key="t" tone="ok">{t('system.tlsOn')}</Badge> : <Badge key="t" tone={r.server.trustedProxies.length ? 'info' : 'warn'}>{r.server.trustedProxies.length ? t('system.tlsProxy') : t('system.tlsOff')}</Badge>],
            [t('system.certificate'), r.server.tlsCert ? <code key="c">{r.server.tlsCert}</code> : '—'],
            [t('system.proxies'), r.server.trustedProxies.length ? r.server.trustedProxies.join(', ') : t('common:none')],
            [t('system.cookieSecure'), r.cookieSecure ? t('common:yes') : t('common:no')],
            [t('system.k8sVersion'), st.data?.kubernetes.version ?? '—'],
            [t('system.podmanVersion'), st.data?.podman.version ?? '—'],
          ]}
        />
        {!r.server.tls && !r.server.trustedProxies.length && r.environment === 'production' && <Alert tone="warn">{t('system.tlsWarning')}</Alert>}
      </Card>
      <Card title={t('system.fileOnly')}>
        <p className="small">{t('system.fileOnlyText')}</p>
        <HelpLink slug="proc-installare" />
      </Card>
    </div>
  );
}

export default function SettingsPage() {
  const { section = 'system' } = useParams();
  const { t } = useTranslation('settings');
  const { can } = useAuth();
  const q = useApi<SettingsData>(can('settings.read') ? '/settings' : null);
  if (!SECTIONS.includes(section)) return <Navigate to="/settings/system" replace />;
  const readOnly = !can('settings.manage');
  const page = PAGES[section];
  return (
    <>
      <PageHeader title={t(`title.${section}`)} subtitle={t(`subtitle.${section}`)} help={page?.guide ? <HelpLink slug={page.guide} /> : undefined} />
      {!can('settings.read') && <Alert tone="warn">{t('common:permissionDenied')}</Alert>}
      {readOnly && can('settings.read') && <Alert tone="info">{t('common:readOnlyHint')}</Alert>}
      {q.isLoading && <Loading />}
      {q.error && <ErrorPanel error={q.error} onRetry={() => void q.refetch()} />}
      {q.data && section === 'system' && <SystemInfo data={q.data} />}
      {q.data && page && (
        <>
          {(section === 'kubernetes' || section === 'podman') && <ConnectionStatus which={section} />}
          {section === 'logging' && (
            <Alert tone="info">
              {q.data.readonly.logFile ? t('logFileAt', { file: q.data.readonly.logFile }) : t('logJournal')}
            </Alert>
          )}
          {section === 'backup' && <Alert tone="info">{t('backupDirAt', { dir: q.data.readonly.backupDirectory })}</Alert>}
          <div className="grid cols-2">
            {page.groups.map((g) => (
              <GroupForm key={g.section} group={g} data={q.data!} readOnly={readOnly} />
            ))}
          </div>
        </>
      )}
    </>
  );
}
