import { useState, type ReactNode } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { CheckCircle2, AlertTriangle, XCircle, CircleHelp, PlugZap } from 'lucide-react';
import { ApiError, api } from '@/api/client';
import { useApi } from '@/hooks/api';
import { setLanguage } from '@/i18n';
import { ErrorPanel } from '@/components/ErrorPanel';
import { Alert, Badge, Card, Field, KeyValue, Loading } from '@/components/ui';
import { classNames, formatBytes } from '@/utils/format';

const STEPS = ['welcome', 'system', 'kubernetes', 'podman', 'auth', 'monitoring', 'backup', 'tls', 'summary', 'test', 'complete'] as const;
type Step = (typeof STEPS)[number];
const USERNAME_RE = /^[A-Za-z0-9][A-Za-z0-9._@-]{1,62}$/;

interface SystemCheck {
  checks: { id: string; status: 'ok' | 'warn' | 'fail'; params: Record<string, unknown> }[];
  version: string;
  config: {
    kubernetes: { enabled: boolean; kubeconfig: string | null; context: string | null; in_cluster: boolean };
    podman: { enabled: boolean; url: string };
    monitoring: { prometheus_url: string | null };
    backup: { directory: string; retention_count: number };
    tls: { enabled: boolean; cert: string | null };
    server: { host: string; port: number };
  };
}

interface ConnInfo {
  connected?: boolean;
  skipped?: boolean;
  version?: { gitVersion?: string } | string | null;
  context?: string | null;
  server?: string | null;
  endpoint?: string | null;
  rootless?: boolean;
  permissions?: Record<string, string>;
  error?: { code: string; message: string; details?: string | null };
  demo?: boolean;
}

interface PromInfo {
  ok?: boolean;
  skipped?: boolean;
  targets?: number;
  latencyMs?: number;
  error?: { code: string; message: string; details?: string | null };
}

const STATUS_ICON: Record<string, ReactNode> = {
  ok: <CheckCircle2 size={16} className="check-ok" aria-hidden="true" />,
  warn: <AlertTriangle size={16} className="check-warn" aria-hidden="true" />,
  fail: <XCircle size={16} className="check-fail" aria-hidden="true" />,
  unknown: <CircleHelp size={16} className="check-unknown" aria-hidden="true" />,
};

function ConnResult({ result, kind }: { result: ConnInfo | null; kind: 'k8s' | 'podman' }) {
  const { t } = useTranslation('setup');
  if (!result) return null;
  if (result.skipped) return <Alert tone="info">{t('test.skipped')}</Alert>;
  if (!result.connected) {
    return (
      <Alert tone="err" title={t('test.failed')}>
        <p>{result.error?.message}</p>
        {result.error?.details && <p className="small mono">{result.error.details}</p>}
        <p className="small">{t(`test.${kind}Hint`)}</p>
      </Alert>
    );
  }
  const version = typeof result.version === 'string' ? result.version : result.version?.gitVersion;
  return (
    <Alert tone="ok" title={t('test.ok')}>
      <p>
        {kind === 'k8s'
          ? t('test.k8sOk', { version, context: result.context ?? '—', server: result.server ?? '—' })
          : t('test.podmanOk', { version, endpoint: result.endpoint ?? '—', mode: result.rootless ? 'rootless' : 'rootful' })}
      </p>
      {result.permissions && (
        <ul className="check-list small">
          {Object.entries(result.permissions).map(([k, v]) => (
            <li key={k}>
              {v === 'ok' ? STATUS_ICON.ok : STATUS_ICON.fail}
              <span>
                {t('test.canList', { kind: k })}: {v === 'ok' ? t('test.allowed') : v}
              </span>
            </li>
          ))}
        </ul>
      )}
    </Alert>
  );
}

function PromResult({ result }: { result: PromInfo | null }) {
  const { t } = useTranslation('setup');
  if (!result) return null;
  if (result.skipped) return <Alert tone="info">{t('test.promSkipped')}</Alert>;
  if (!result.ok) return <Alert tone="err" title={t('test.failed')}>{result.error?.message}</Alert>;
  return <Alert tone="ok" title={t('test.ok')}>{t('test.promOk', { targets: result.targets, ms: result.latencyMs })}</Alert>;
}

export default function SetupWizard() {
  const { t, i18n } = useTranslation('setup');
  const navigate = useNavigate();
  const qc = useQueryClient();
  const status = useApi<{ setupRequired: boolean; tokenIssued: boolean; mode: string }>('/setup/status', undefined, { refetchInterval: false });
  const [step, setStep] = useState<Step>('welcome');
  const [visited, setVisited] = useState<Set<Step>>(new Set(['welcome']));
  const [token, setToken] = useState('');
  const [tokenOk, setTokenOk] = useState(false);
  const [tokenError, setTokenError] = useState<string | null>(null);
  const [sys, setSys] = useState<SystemCheck | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [k8s, setK8s] = useState({ enabled: true, kubeconfig: '/etc/pkm/kubeconfig', context: '', in_cluster: false });
  const [k8sResult, setK8sResult] = useState<ConnInfo | null>(null);
  const [podman, setPodman] = useState({ enabled: true, url: 'unix:///run/podman/podman.sock' });
  const [podResult, setPodResult] = useState<ConnInfo | null>(null);
  const [admin, setAdmin] = useState({ username: 'admin', password: '', repeat: '', display_name: '', email: '' });
  const [promUrl, setPromUrl] = useState('');
  const [promResult, setPromResult] = useState<PromInfo | null>(null);
  const [retention, setRetention] = useState(14);
  const [done, setDone] = useState(false);

  const call = <T,>(path: string, method: 'GET' | 'POST' = 'GET', body?: unknown) =>
    api<T>(`/setup${path}`, { method, body, headers: { 'X-Setup-Token': token.trim() }, timeoutMs: 60_000 });

  const idx = STEPS.indexOf(step);
  const go = (s: Step) => {
    setError(null);
    setStep(s);
    setVisited((v) => new Set(v).add(s));
    document.getElementById('setup-step-title')?.focus();
  };

  const verifyToken = async () => {
    setBusy(true);
    setTokenError(null);
    try {
      await call('/verify-token', 'POST');
      setTokenOk(true);
      const s = await call<SystemCheck>('/system-check');
      setSys(s);
      setK8s({ enabled: s.config.kubernetes.enabled, kubeconfig: s.config.kubernetes.kubeconfig ?? '', context: s.config.kubernetes.context ?? '', in_cluster: s.config.kubernetes.in_cluster });
      setPodman({ enabled: s.config.podman.enabled, url: s.config.podman.url });
      setPromUrl(s.config.monitoring.prometheus_url ?? '');
      setRetention(s.config.backup.retention_count);
    } catch (e) {
      setTokenOk(false);
      if (e instanceof ApiError && e.status === 403) setTokenError(t('token.invalid'));
      else if (e instanceof ApiError && e.code === 'rate_limited') setTokenError(t('token.rateLimited', { seconds: e.params.retryAfter }));
      else setTokenError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const k8sBody = () => ({ enabled: k8s.enabled, kubeconfig: k8s.kubeconfig.trim() || null, context: k8s.context.trim() || null, in_cluster: k8s.in_cluster });
  const testK8s = async () => {
    setBusy(true);
    setK8sResult(null);
    try {
      setK8sResult(await call<ConnInfo>('/test-kubernetes', 'POST', k8sBody()));
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };
  const testPodman = async () => {
    setBusy(true);
    setPodResult(null);
    try {
      setPodResult(await call<ConnInfo>('/test-podman', 'POST', podman));
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };
  const testProm = async () => {
    setBusy(true);
    setPromResult(null);
    try {
      setPromResult(await call<PromInfo>('/test-prometheus', 'POST', { prometheus_url: promUrl.trim() || null }));
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };
  const runAllTests = async () => {
    await testK8s();
    await testPodman();
    await testProm();
  };

  const adminErrors: Record<string, string> = {};
  if (!USERNAME_RE.test(admin.username)) adminErrors.username = t('auth.errUsername');
  if (admin.password.length < 12) adminErrors.password = t('auth.errPassword');
  if (admin.password !== admin.repeat) adminErrors.repeat = t('auth.errRepeat');
  const adminValid = Object.keys(adminErrors).length === 0;

  const complete = async () => {
    setBusy(true);
    setError(null);
    try {
      await call('/complete', 'POST', {
        admin: { username: admin.username, password: admin.password, display_name: admin.display_name, email: admin.email },
        language: i18n.language === 'en' ? 'en' : 'it',
        kubernetes: k8sBody(),
        podman,
        monitoring: { prometheus_url: promUrl.trim() || null },
        backup_retention_count: retention,
      });
      setDone(true);
      setAdmin((a) => ({ ...a, password: '', repeat: '' }));
      await qc.invalidateQueries({ queryKey: ['/system/info'] });
    } catch (e) {
      if (e instanceof ApiError && e.params.problems) {
        const msg = (e.params.problems as string[]).map((p) => t(`auth:policy.${p}`, { min: e.params.min_length })).join(' ');
        setError(new ApiError(e.status, { code: e.code, message: msg, requestId: e.requestId }));
        go('auth');
      } else setError(e);
    } finally {
      setBusy(false);
    }
  };

  const canNext = (): boolean => {
    if (step === 'system') return tokenOk;
    if (step === 'auth') return adminValid;
    return true;
  };

  if (status.isLoading) return <Loading />;
  if (status.data && !status.data.setupRequired && !done) {
    return (
      <div className="login-page">
        <Card title={t('already.title')}>
          <p>{t('already.text')}</p>
          <Link className="btn primary" to="/login">
            {t('goLogin')}
          </Link>
        </Card>
      </div>
    );
  }

  let body: ReactNode = null;
  switch (step) {
    case 'welcome':
      body = (
        <>
          <p>{t('welcome.text')}</p>
          <ul>
            {(t('welcome.points', { returnObjects: true }) as string[]).map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
          {status.data?.mode === 'demo' && <Alert tone="purple">{t('welcome.demo')}</Alert>}
          <Field label={t('common:language')} htmlFor="setup-lang">
            <select id="setup-lang" className="input" style={{ maxWidth: 220 }} value={i18n.language} onChange={(e) => setLanguage(e.target.value as 'it' | 'en')}>
              <option value="it">Italiano</option>
              <option value="en">English</option>
            </select>
          </Field>
        </>
      );
      break;
    case 'system':
      body = (
        <>
          <p>{t('token.text')}</p>
          <pre className="code">sudo pkm-admin setup-token</pre>
          <div className="row" style={{ alignItems: 'flex-end' }}>
            <Field label={t('token.label')} htmlFor="setup-token" error={tokenError ?? undefined}>
              <input
                id="setup-token"
                className="input mono"
                style={{ minWidth: 300 }}
                value={token}
                autoComplete="off"
                spellCheck={false}
                aria-invalid={!!tokenError}
                onChange={(e) => {
                  setToken(e.target.value);
                  setTokenOk(false);
                }}
                onKeyDown={(e) => e.key === 'Enter' && token.trim() && void verifyToken()}
              />
            </Field>
            <button type="button" className="btn primary" style={{ marginBottom: 14 }} disabled={!token.trim() || busy} onClick={() => void verifyToken()}>
              {busy && <span className="spinner" aria-hidden="true" />} {t('token.verify')}
            </button>
          </div>
          {sys && (
            <div aria-live="polite">
              <h3>{t('system.title')}</h3>
              <ul className="check-list">
                {sys.checks.map((c) => (
                  <li key={c.id}>
                    {STATUS_ICON[c.status] ?? STATUS_ICON.unknown}
                    <div>
                      <strong>{t(`system.check.${c.id}`)}</strong>
                      <div className="small muted">
                        {t(`system.detail.${c.id}.${c.status}`, {
                          ...c.params,
                          freeBytes: formatBytes(Number(c.params.freeBytes ?? 0)),
                          defaultValue: JSON.stringify(c.params),
                        })}
                      </div>
                    </div>
                  </li>
                ))}
              </ul>
              <p className="small muted">{t('system.optionalNote')}</p>
            </div>
          )}
        </>
      );
      break;
    case 'kubernetes':
      body = (
        <>
          <p>{t('k8s.text')}</p>
          <label className="checkbox" style={{ marginBottom: 12 }}>
            <input type="checkbox" checked={k8s.enabled} onChange={(e) => setK8s({ ...k8s, enabled: e.target.checked })} />
            {t('k8s.enable')}
          </label>
          {k8s.enabled && (
            <>
              <label className="checkbox" style={{ marginBottom: 12 }}>
                <input type="checkbox" checked={k8s.in_cluster} onChange={(e) => setK8s({ ...k8s, in_cluster: e.target.checked })} />
                {t('k8s.inCluster')}
              </label>
              {!k8s.in_cluster && (
                <div className="form-grid">
                  <Field label={t('k8s.kubeconfig')} htmlFor="s-kc" hint={t('k8s.kubeconfigHint')}>
                    <input id="s-kc" className="input mono" value={k8s.kubeconfig} onChange={(e) => setK8s({ ...k8s, kubeconfig: e.target.value })} spellCheck={false} />
                  </Field>
                  <Field label={t('k8s.context')} htmlFor="s-ctx" hint={t('k8s.contextHint')}>
                    <input id="s-ctx" className="input" value={k8s.context} onChange={(e) => setK8s({ ...k8s, context: e.target.value })} />
                  </Field>
                </div>
              )}
            </>
          )}
          <button type="button" className="btn" onClick={() => void testK8s()} disabled={busy}>
            {busy ? <span className="spinner" aria-hidden="true" /> : <PlugZap size={14} />} {t('test.run')}
          </button>
          <div aria-live="polite" style={{ marginTop: 12 }}>
            <ConnResult result={k8sResult} kind="k8s" />
          </div>
          <p className="small muted">{t('k8s.optional')}</p>
        </>
      );
      break;
    case 'podman':
      body = (
        <>
          <p>{t('podman.text')}</p>
          <label className="checkbox" style={{ marginBottom: 12 }}>
            <input type="checkbox" checked={podman.enabled} onChange={(e) => setPodman({ ...podman, enabled: e.target.checked })} />
            {t('podman.enable')}
          </label>
          {podman.enabled && (
            <Field label={t('podman.url')} htmlFor="s-pod" hint={t('podman.urlHint')}>
              <input id="s-pod" className="input mono" value={podman.url} onChange={(e) => setPodman({ ...podman, url: e.target.value })} spellCheck={false} />
            </Field>
          )}
          <Alert tone="warn">{t('podman.rootWarning')}</Alert>
          <button type="button" className="btn" onClick={() => void testPodman()} disabled={busy}>
            {busy ? <span className="spinner" aria-hidden="true" /> : <PlugZap size={14} />} {t('test.run')}
          </button>
          <div aria-live="polite" style={{ marginTop: 12 }}>
            <ConnResult result={podResult} kind="podman" />
          </div>
        </>
      );
      break;
    case 'auth':
      body = (
        <>
          <p>{t('auth.text')}</p>
          <div className="form-grid">
            <Field label={t('auth.username')} htmlFor="s-user" error={admin.username ? adminErrors.username : undefined}>
              <input id="s-user" className="input" value={admin.username} autoComplete="username" onChange={(e) => setAdmin({ ...admin, username: e.target.value })} aria-invalid={!!adminErrors.username} />
            </Field>
            <Field label={t('auth.displayName')} htmlFor="s-dn">
              <input id="s-dn" className="input" value={admin.display_name} onChange={(e) => setAdmin({ ...admin, display_name: e.target.value })} />
            </Field>
            <Field label={t('auth.email')} htmlFor="s-email">
              <input id="s-email" className="input" type="email" value={admin.email} onChange={(e) => setAdmin({ ...admin, email: e.target.value })} />
            </Field>
          </div>
          <div className="form-grid">
            <Field label={t('auth.password')} htmlFor="s-pw" hint={t('auth:policyHint')} error={admin.password ? adminErrors.password : undefined}>
              <input id="s-pw" className="input" type="password" autoComplete="new-password" value={admin.password} onChange={(e) => setAdmin({ ...admin, password: e.target.value })} aria-invalid={!!admin.password && !!adminErrors.password} />
            </Field>
            <Field label={t('auth.repeat')} htmlFor="s-pw2" error={admin.repeat ? adminErrors.repeat : undefined}>
              <input id="s-pw2" className="input" type="password" autoComplete="new-password" value={admin.repeat} onChange={(e) => setAdmin({ ...admin, repeat: e.target.value })} aria-invalid={!!admin.repeat && !!adminErrors.repeat} />
            </Field>
          </div>
          <p className="small muted">{t('auth.note')}</p>
        </>
      );
      break;
    case 'monitoring':
      body = (
        <>
          <p>{t('monitoring.text')}</p>
          <Field label={t('monitoring.url')} htmlFor="s-prom" hint={t('monitoring.urlHint')}>
            <input id="s-prom" className="input mono" value={promUrl} placeholder="http://prometheus.monitoring.svc:9090" onChange={(e) => setPromUrl(e.target.value)} spellCheck={false} />
          </Field>
          <button type="button" className="btn" onClick={() => void testProm()} disabled={busy || !promUrl.trim()}>
            {busy ? <span className="spinner" aria-hidden="true" /> : <PlugZap size={14} />} {t('test.run')}
          </button>
          <div aria-live="polite" style={{ marginTop: 12 }}>
            <PromResult result={promResult} />
          </div>
        </>
      );
      break;
    case 'backup':
      body = (
        <>
          <p>{t('backup.text')}</p>
          <ul>
            {(t('backup.contents', { returnObjects: true }) as string[]).map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ul>
          <Alert tone="warn">{t('backup.notCluster')}</Alert>
          <Field label={t('backup.retention')} htmlFor="s-ret" hint={t('backup.retentionHint', { dir: sys?.config.backup.directory ?? '/var/lib/pkm/backups' })}>
            <input id="s-ret" className="input" type="number" min={1} max={1000} style={{ maxWidth: 160 }} value={retention} onChange={(e) => setRetention(Math.max(1, Math.min(1000, Number(e.target.value) || 1)))} />
          </Field>
          <p className="small muted">{t('backup.timer')}</p>
        </>
      );
      break;
    case 'tls':
      body = (
        <>
          {sys?.config.tls.enabled ? (
            <Alert tone="ok" title={t('tls.on')}>
              {t('tls.cert', { cert: sys.config.tls.cert })}
            </Alert>
          ) : (
            <Alert tone="warn" title={t('tls.off')}>
              {t('tls.offText')}
            </Alert>
          )}
          <p>{t('tls.text')}</p>
          <pre className="code">{t('tls.commands')}</pre>
          <p className="small muted">{t('tls.proxy')}</p>
        </>
      );
      break;
    case 'summary':
      body = (
        <>
          <p>{t('summary.text')}</p>
          <KeyValue
            items={[
              [t('summary.admin'), admin.username],
              [t('common:language'), i18n.language === 'en' ? 'English' : 'Italiano'],
              ['Kubernetes', k8s.enabled ? (k8s.in_cluster ? t('k8s.inCluster') : `${k8s.kubeconfig || '—'}${k8s.context ? ` (${k8s.context})` : ''}`) : t('summary.disabled')],
              ['Podman', podman.enabled ? podman.url : t('summary.disabled')],
              ['Prometheus', promUrl.trim() || t('summary.notConfigured')],
              [t('summary.retention'), retention],
              ['TLS', sys?.config.tls.enabled ? t('tls.on') : t('tls.off')],
              [t('summary.listen'), sys ? `${sys.config.server.host}:${sys.config.server.port}` : '—'],
            ]}
          />
          {status.data?.mode === 'demo' && <Alert tone="purple">{t('summary.demoNote')}</Alert>}
        </>
      );
      break;
    case 'test':
      body = (
        <>
          <p>{t('testStep.text')}</p>
          <button type="button" className="btn" onClick={() => void runAllTests()} disabled={busy}>
            {busy ? <span className="spinner" aria-hidden="true" /> : <PlugZap size={14} />} {t('testStep.runAll')}
          </button>
          <div aria-live="polite" style={{ marginTop: 12 }}>
            <h3>Kubernetes</h3>
            {k8sResult ? <ConnResult result={k8sResult} kind="k8s" /> : <p className="muted small">{t('testStep.notRun')}</p>}
            <h3>Podman</h3>
            {podResult ? <ConnResult result={podResult} kind="podman" /> : <p className="muted small">{t('testStep.notRun')}</p>}
            <h3>Prometheus</h3>
            {promResult ? <PromResult result={promResult} /> : <p className="muted small">{promUrl.trim() ? t('testStep.notRun') : t('test.promSkipped')}</p>}
          </div>
          <p className="small muted">{t('testStep.nonBlocking')}</p>
        </>
      );
      break;
    case 'complete':
      body = done ? (
        <>
          <Alert tone="ok" title={t('done.title')}>
            {t('done.text', { user: admin.username })}
          </Alert>
          <button type="button" className="btn primary" onClick={() => navigate('/login', { replace: true })}>
            {t('goLogin')}
          </button>
        </>
      ) : (
        <>
          <p>{t('complete.text')}</p>
          <button type="button" className="btn primary" onClick={() => void complete()} disabled={busy || !adminValid || !tokenOk}>
            {busy && <span className="spinner" aria-hidden="true" />} {t('complete.button')}
          </button>
          {!tokenOk && <p className="small check-fail">{t('complete.needToken')}</p>}
          {!adminValid && <p className="small check-fail">{t('complete.needAdmin')}</p>}
        </>
      );
      break;
  }

  return (
    <div className="login-page" style={{ alignItems: 'flex-start' }}>
      <main className="card" style={{ width: 'min(1040px, 100%)' }}>
        {status.data?.mode === 'demo' && <div className="demo-banner">{t('common:demoBanner')}</div>}
        <div className="card-header">
          <h1 style={{ margin: 0, fontSize: 18 }}>{t('title')}</h1>
          <span className="small muted" style={{ marginLeft: 'auto' }}>
            {t('stepOf', { n: idx + 1, total: STEPS.length })}
          </span>
        </div>
        <div className="card-body">
          <div className="wizard">
            <nav aria-label={t('stepsLabel')}>
              <ol className="wizard-steps">
                {STEPS.map((s, i) => {
                  const reachable = visited.has(s) && !done;
                  return (
                    <li key={s} className={classNames(s === step && 'current', i < idx && 'done')} aria-current={s === step ? 'step' : undefined}>
                      {reachable && s !== step ? (
                        <button type="button" onClick={() => go(s)}>
                          <span className="num">{i + 1}</span>
                          <span className="txt">{t(`steps.${s}`)}</span>
                        </button>
                      ) : (
                        <>
                          <span className="num">{i + 1}</span>
                          <span className="txt">{t(`steps.${s}`)}</span>
                        </>
                      )}
                    </li>
                  );
                })}
              </ol>
            </nav>
            <section aria-labelledby="setup-step-title">
              <h2 id="setup-step-title" tabIndex={-1}>
                {t(`steps.${step}`)} {step === 'kubernetes' || step === 'podman' || step === 'monitoring' ? <Badge tone="muted">{t('optional')}</Badge> : null}
              </h2>
              {body}
              {error ? <div style={{ marginTop: 12 }}><ErrorPanel error={error} /></div> : null}
              {!done && (
                <div className="wizard-nav">
                  <button type="button" className="btn" disabled={idx === 0 || busy} onClick={() => go(STEPS[idx - 1])}>
                    {t('common:back')}
                  </button>
                  {idx < STEPS.length - 1 && (
                    <button type="button" className="btn primary" disabled={!canNext() || busy} onClick={() => go(STEPS[idx + 1])} title={!canNext() ? t(`blocked.${step}`, { defaultValue: '' }) : undefined}>
                      {t('common:next')}
                    </button>
                  )}
                </div>
              )}
              {!canNext() && <p className="small muted" style={{ textAlign: 'right' }}>{t(`blocked.${step}`, { defaultValue: '' })}</p>}
            </section>
          </div>
        </div>
      </main>
    </div>
  );
}
