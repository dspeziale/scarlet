import { useState, type FormEvent } from 'react';
import { Navigate, useLocation, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { LogIn } from 'lucide-react';
import { ApiError } from '@/api/client';
import type { SystemInfo } from '@/api/types';
import { useAuth } from '@/auth/AuthContext';
import { useApi } from '@/hooks/api';
import { Alert, Field } from '@/components/ui';
import { setLanguage } from '@/i18n';

export default function Login() {
  const { t, i18n } = useTranslation('auth');
  const { session, login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const info = useApi<SystemInfo>('/system/info');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const from = (location.state as { from?: string } | null)?.from ?? '/';

  if (session) return <Navigate to={from} replace />;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(username.trim(), password);
      navigate(from, { replace: true });
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.code === 'rate_limited') setError(t('rateLimited', { seconds: err.params.retryAfter }));
        else if (err.params.reason === 'locked') setError(t('locked'));
        else if (err.status === 401) setError(t('invalid'));
        else setError(err.message);
      } else setError(String(err));
    } finally {
      setBusy(false);
      setPassword('');
    }
  };

  return (
    <div className="login-page">
      <main className="card login-card">
        {info.data?.mode === 'demo' && <div className="demo-banner">{t('common:demoBanner')}</div>}
        <div className="card-body" style={{ padding: 28 }}>
          <div className="row between" style={{ marginBottom: 18 }}>
            <h1 style={{ margin: 0 }}>{info.data?.appName ?? 'Podman Kubernetes Manager'}</h1>
            <select className="input sm" aria-label={t('common:language')} value={i18n.language} onChange={(e) => setLanguage(e.target.value as 'it' | 'en')}>
              <option value="it">IT</option>
              <option value="en">EN</option>
            </select>
          </div>
          <p className="muted">{t('subtitle')}</p>
          {error && <Alert tone="err">{error}</Alert>}
          <form onSubmit={(e) => void submit(e)} noValidate>
            <Field label={t('username')} htmlFor="login-user">
              <input id="login-user" className="input" autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} required autoFocus />
            </Field>
            <Field label={t('password')} htmlFor="login-pass">
              <input id="login-pass" className="input" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
            </Field>
            <button type="submit" className="btn primary" style={{ width: '100%', height: 38 }} disabled={busy || !username || !password}>
              {busy ? <span className="spinner" aria-hidden="true" /> : <LogIn size={16} />} {t('signIn')}
            </button>
          </form>
          <p className="small muted" style={{ marginTop: 16 }}>
            {t('forgotten')}
          </p>
          {info.data && (
            <p className="small muted" style={{ margin: 0 }}>
              v{info.data.version} · API {info.data.apiVersion} · {info.data.mode.toUpperCase()}
            </p>
          )}
        </div>
      </main>
    </div>
  );
}
