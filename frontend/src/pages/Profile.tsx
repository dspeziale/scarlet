import { useState, type FormEvent } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { ApiError, patch, post } from '@/api/client';
import type { SessionInfo } from '@/api/types';
import { useAuth } from '@/auth/AuthContext';
import { useAction, useApi } from '@/hooks/api';
import { Alert, Card, Field, KeyValue, PageHeader } from '@/components/ui';
import { DataTable } from '@/components/DataTable';
import { formatDate } from '@/utils/format';
import { setLanguage } from '@/i18n';

interface SessionRow {
  id: string;
  created_at: string;
  last_seen_at: string;
  expires_at: string;
  ip: string;
  user_agent: string;
  current: boolean;
}

export default function Profile() {
  const { t } = useTranslation('auth');
  const { user, session, setSession } = useAuth();
  const [params] = useSearchParams();
  const mustChange = !!user?.must_change_password || params.get('mustChange') === '1';
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [repeat, setRepeat] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const sessions = useApi<{ items: SessionRow[] }>('/auth/sessions');
  const revoke = useAction(() => post('/auth/sessions/revoke-others'), { success: t('revoked') });
  const lang = useAction((language: 'it' | 'en') => patch('/auth/me', { language }), {
    onSuccess: () => undefined,
  });

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setDone(false);
    if (next !== repeat) {
      setError(t('mismatch'));
      return;
    }
    try {
      const s = await post<SessionInfo>('/auth/change-password', { current_password: current, new_password: next });
      setSession(s);
      setDone(true);
      setCurrent('');
      setNext('');
      setRepeat('');
    } catch (err) {
      if (err instanceof ApiError && err.params.problems) {
        setError((err.params.problems as string[]).map((p) => t(`policy.${p}`, { min: err.params.min_length })).join(' '));
      } else if (err instanceof ApiError && err.params.field === 'current_password') setError(t('wrongCurrent'));
      else if (err instanceof ApiError) setError(err.message);
      else setError(String(err));
    }
  };

  return (
    <>
      <PageHeader title={t('profileTitle')} subtitle={user?.display_name || user?.username} />
      {mustChange && !done && <Alert tone="warn" title={t('mustChangeTitle')}>{t('mustChangeText')}</Alert>}
      <div className="grid cols-2">
        <Card title={t('account')}>
          <KeyValue
            items={[
              [t('username'), user?.username],
              [t('role'), t(`common:roles.${user?.role}`)],
              [t('lastLogin'), formatDate(user?.last_login_at)],
              [t('sessionExpires'), formatDate(session?.expiresAt)],
              [t('permissionsCount'), session?.permissions.length],
            ]}
          />
          <div className="field" style={{ marginTop: 14 }}>
            <label htmlFor="pref-lang">{t('common:language')}</label>
            <select
              id="pref-lang"
              className="input"
              value={user?.language}
              onChange={(e) => {
                const l = e.target.value as 'it' | 'en';
                setLanguage(l);
                void lang.run(l);
              }}
            >
              <option value="it">Italiano</option>
              <option value="en">English</option>
            </select>
          </div>
        </Card>
        <Card title={t('changePassword')}>
          {done && <Alert tone="ok">{t('passwordChanged')}</Alert>}
          {error && <Alert tone="err">{error}</Alert>}
          <form onSubmit={(e) => void submit(e)}>
            <Field label={t('currentPassword')} htmlFor="pw-cur">
              <input id="pw-cur" className="input" type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} />
            </Field>
            <Field label={t('newPassword')} htmlFor="pw-new" hint={t('policyHint')}>
              <input id="pw-new" className="input" type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} />
            </Field>
            <Field label={t('repeatPassword')} htmlFor="pw-rep">
              <input id="pw-rep" className="input" type="password" autoComplete="new-password" value={repeat} onChange={(e) => setRepeat(e.target.value)} />
            </Field>
            <button className="btn primary" type="submit" disabled={!current || !next || !repeat}>
              {t('changePassword')}
            </button>
          </form>
        </Card>
      </div>
      <div className="section" style={{ marginTop: 14 }}>
        <Card
          title={t('sessions')}
          flush
          actions={
            <button className="btn sm" onClick={() => void revoke.run()} disabled={revoke.busy}>
              {t('revokeOthers')}
            </button>
          }
        >
          <DataTable
            rows={sessions.data?.items ?? []}
            rowKey={(r) => r.id}
            columns={[
              { id: 'id', header: 'ID', cell: (r) => <code>{r.id}</code> },
              { id: 'ip', header: 'IP', cell: (r) => r.ip, value: (r) => r.ip },
              { id: 'ua', header: t('browser'), cell: (r) => <span className="ellipsis" style={{ maxWidth: 320, display: 'inline-block' }} title={r.user_agent}>{r.user_agent}</span> },
              { id: 'seen', header: t('lastSeen'), cell: (r) => formatDate(r.last_seen_at), value: (r) => r.last_seen_at },
              { id: 'cur', header: '', cell: (r) => (r.current ? <span className="badge tone-ok">{t('thisSession')}</span> : null) },
            ]}
          />
        </Card>
      </div>
    </>
  );
}
