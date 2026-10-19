import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Download } from 'lucide-react';
import { downloadUrl } from '@/api/client';
import { useAuth } from '@/auth/AuthContext';
import { useApi, useDebounced } from '@/hooks/api';
import { Dialog } from '@/components/Dialog';
import { ErrorPanel } from '@/components/ErrorPanel';
import { Alert, Badge, Card, Empty, Field, KeyValue, Loading, PageHeader, type Tone } from '@/components/ui';
import { formatDate } from '@/utils/format';

interface AuditEntry {
  id: number;
  ts: string;
  user_id: number | null;
  username: string;
  action: string;
  resource_kind: string;
  resource_name: string;
  namespace: string;
  result: 'success' | 'failure' | 'denied';
  detail: unknown;
  ip: string;
  user_agent: string;
  session_ref: string;
  request_id: string;
}

interface AuditPage {
  items: AuditEntry[];
  total: number;
  limit: number;
  offset: number;
  actions: string[];
  retentionDays: number;
}

const RESULT_TONE: Record<string, Tone> = { success: 'ok', failure: 'err', denied: 'warn' };
const PAGE = 50;

export default function Audit() {
  const { t } = useTranslation('security');
  const { can } = useAuth();
  const [q, setQ] = useState('');
  const [username, setUsername] = useState('');
  const [action, setAction] = useState('');
  const [result, setResult] = useState('');
  const [namespace, setNamespace] = useState('');
  const [since, setSince] = useState('');
  const [until, setUntil] = useState('');
  const [offset, setOffset] = useState(0);
  const [open, setOpen] = useState<AuditEntry | null>(null);
  const dq = useDebounced(q, 300);
  const dUser = useDebounced(username, 300);
  const dNs = useDebounced(namespace, 300);
  const filters = {
    q: dq || undefined,
    username: dUser || undefined,
    action: action || undefined,
    result: result || undefined,
    namespace: dNs || undefined,
    since: since ? `${since}T00:00:00` : undefined,
    until: until ? `${until}T23:59:59` : undefined,
  };
  const data = useApi<AuditPage>(can('audit.read') ? '/audit' : null, { ...filters, limit: PAGE, offset });

  if (!can('audit.read')) {
    return (
      <>
        <PageHeader title={t('audit.title')} />
        <Alert tone="warn">{t('common:permissionDenied')}</Alert>
      </>
    );
  }

  const resetPage = <T,>(fn: (v: T) => void) => (v: T) => {
    fn(v);
    setOffset(0);
  };
  const describe = (e: AuditEntry) =>
    t(`audit.actions.${e.action.replace(/\./g, '_')}`, {
      defaultValue: e.action,
      user: e.username,
      kind: e.resource_kind,
      name: e.resource_name,
      namespace: e.namespace,
    });

  return (
    <>
      <PageHeader
        title={t('audit.title')}
        subtitle={t('audit.subtitle', { days: data.data?.retentionDays ?? '—' })}
        actions={
          <button type="button" className="btn" onClick={() => downloadUrl('/audit/export.csv', filters)}>
            <Download size={14} /> {t('audit.export')}
          </button>
        }
      />
      <Card title={t('audit.filters')}>
        <div className="form-grid">
          <Field label={t('common:search')} htmlFor="a-q">
            <input id="a-q" className="input" value={q} onChange={(e) => resetPage(setQ)(e.target.value)} placeholder={t('audit.searchHint')} />
          </Field>
          <Field label={t('audit.user')} htmlFor="a-user">
            <input id="a-user" className="input" value={username} onChange={(e) => resetPage(setUsername)(e.target.value)} />
          </Field>
          <Field label={t('audit.action')} htmlFor="a-action">
            <select id="a-action" className="input" value={action} onChange={(e) => resetPage(setAction)(e.target.value)}>
              <option value="">{t('common:all')}</option>
              {(data.data?.actions ?? []).map((a) => (
                <option key={a} value={a}>
                  {a}
                </option>
              ))}
            </select>
          </Field>
          <Field label={t('audit.result')} htmlFor="a-result">
            <select id="a-result" className="input" value={result} onChange={(e) => resetPage(setResult)(e.target.value)}>
              <option value="">{t('common:all')}</option>
              {['success', 'failure', 'denied'].map((r) => (
                <option key={r} value={r}>
                  {t(`audit.results.${r}`)}
                </option>
              ))}
            </select>
          </Field>
          <Field label={t('common:namespace')} htmlFor="a-ns">
            <input id="a-ns" className="input" value={namespace} onChange={(e) => resetPage(setNamespace)(e.target.value)} />
          </Field>
          <Field label={t('audit.since')} htmlFor="a-since">
            <input id="a-since" className="input" type="date" value={since} onChange={(e) => resetPage(setSince)(e.target.value)} />
          </Field>
          <Field label={t('audit.until')} htmlFor="a-until">
            <input id="a-until" className="input" type="date" value={until} onChange={(e) => resetPage(setUntil)(e.target.value)} />
          </Field>
        </div>
      </Card>
      <div className="section" style={{ marginTop: 14 }}>
        <Card flush>
          {data.isLoading && <Loading />}
          {data.error && <div style={{ padding: 12 }}><ErrorPanel error={data.error} onRetry={() => void data.refetch()} /></div>}
          {data.data && data.data.items.length === 0 && <Empty>{t('audit.none')}</Empty>}
          {data.data && data.data.items.length > 0 && (
            <div className="table-wrap">
              <table className="data">
                <caption className="sr-only">{t('audit.title')}</caption>
                <thead>
                  <tr>
                    <th scope="col">{t('audit.when')}</th>
                    <th scope="col">{t('audit.user')}</th>
                    <th scope="col">{t('audit.event')}</th>
                    <th scope="col">{t('audit.resource')}</th>
                    <th scope="col">{t('audit.result')}</th>
                    <th scope="col">IP</th>
                  </tr>
                </thead>
                <tbody>
                  {data.data.items.map((e) => (
                    <tr key={e.id} className="clickable" tabIndex={0} onClick={() => setOpen(e)} onKeyDown={(ev) => ev.key === 'Enter' && setOpen(e)}>
                      <td className="nowrap">{formatDate(e.ts)}</td>
                      <td>
                        <strong>{e.username}</strong>
                      </td>
                      <td>
                        <div>{describe(e)}</div>
                        <code className="small muted">{e.action}</code>
                      </td>
                      <td className="small">
                        {e.resource_kind && `${e.resource_kind}/`}
                        {e.resource_name}
                        {e.namespace && <span className="chip">{e.namespace}</span>}
                      </td>
                      <td>
                        <Badge tone={RESULT_TONE[e.result]}>{t(`audit.results.${e.result}`)}</Badge>
                      </td>
                      <td className="small">{e.ip}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {data.data && (
            <div className="table-footer">
              <span>{t('audit.range', { from: data.data.total ? offset + 1 : 0, to: Math.min(offset + PAGE, data.data.total), total: data.data.total })}</span>
              <span className="row">
                <button type="button" className="btn sm" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>
                  {t('common:prev')}
                </button>
                <button type="button" className="btn sm" disabled={offset + PAGE >= data.data.total} onClick={() => setOffset(offset + PAGE)}>
                  {t('common:next')}
                </button>
              </span>
            </div>
          )}
        </Card>
      </div>
      {open && (
        <Dialog title={t('audit.detailTitle', { id: open.id })} onClose={() => setOpen(null)} wide>
          <p>{describe(open)}</p>
          <KeyValue
            items={[
              [t('audit.when'), formatDate(open.ts)],
              [t('audit.user'), open.username],
              [t('audit.action'), <code key="a">{open.action}</code>],
              [t('audit.resource'), `${open.resource_kind}/${open.resource_name}`],
              [t('common:namespace'), open.namespace || '—'],
              [t('audit.result'), <Badge key="r" tone={RESULT_TONE[open.result]}>{t(`audit.results.${open.result}`)}</Badge>],
              ['IP', open.ip || '—'],
              [t('audit.client'), open.user_agent || '—'],
              [t('audit.session'), open.session_ref || '—'],
              [t('audit.requestId'), open.request_id || '—'],
            ]}
          />
          <h3 className="small" style={{ marginTop: 14 }}>{t('audit.detail')}</h3>
          <pre className="code">{JSON.stringify(open.detail, null, 2)}</pre>
        </Dialog>
      )}
    </>
  );
}
