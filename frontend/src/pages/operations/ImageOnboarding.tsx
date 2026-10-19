import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { ArrowLeft, ArrowRight, Copy, KeyRound, RefreshCw, Rocket, ShieldAlert } from 'lucide-react';
import { get, post } from '@/api/client';
import { useAuth } from '@/auth/AuthContext';
import { useApi } from '@/hooks/api';
import { Alert, Badge, Card, Field, KeyValue, Loading, PageHeader, type Tone } from '@/components/ui';
import { ErrorPanel } from '@/components/ErrorPanel';
import { CheckList } from '@/components/IssueCard';
import { HelpLink } from '@/components/HelpLink';
import { NamespaceSelect } from '@/components/NamespaceSelect';
import type { Check } from '@/api/types';
import { formatBytes } from '@/utils/format';
import { WizardSteps } from './WizardSteps';
import { choiceToSpec, isDnsLabel, suggestDestination, type ImageConfig, type OnboardingChoice } from './logic';
import '@/styles/pages-b.css';

interface Risk {
  level: 'low' | 'medium' | 'high';
  code: string;
  params?: Record<string, unknown>;
}

interface InspectResult {
  image: string;
  reference?: { registry?: string; repository?: string; tag?: string | null; valid?: boolean };
  checks: Check[];
  config: (ImageConfig & {
    architecture?: string;
    os?: string;
    created?: string;
    entrypoint?: string[];
    cmd?: string[];
    workingDir?: string;
    labels?: Record<string, string>;
  }) | null;
  risks: Risk[];
  size?: number;
  layers?: number;
  platforms?: string[];
  digest?: string;
  demo?: boolean;
  source: 'registry' | 'local';
}

interface LocalImage {
  id: string;
  tags: string[];
  size: number;
  created: number;
  dangling: boolean;
}

const LEVEL_TONE: Record<string, Tone> = { high: 'err', medium: 'warn', low: 'info' };
const BLOCKING = new Set(['image_format', 'registry_reachable', 'registry_auth', 'tag_exists', 'platform_amd64', 'manifest_readable']);

export default function ImageOnboarding() {
  const { t } = useTranslation('onboarding');
  const navigate = useNavigate();
  const { can } = useAuth();
  const [params] = useSearchParams();
  const STEPS = [t('steps.source'), t('steps.verify'), t('steps.analysis'), t('steps.destination'), t('steps.summary')];
  const [step, setStep] = useState(0);
  const [maxReached, setMaxReached] = useState(0);
  const [source, setSource] = useState<'registry' | 'local'>('registry');
  const [imageRef, setImageRef] = useState(params.get('image') ?? '');
  const [localId, setLocalId] = useState<string>('');
  const [useCreds, setUseCreds] = useState(false);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [result, setResult] = useState<InspectResult | null>(null);
  const [inspecting, setInspecting] = useState(false);
  const [inspectError, setInspectError] = useState<unknown>(null);
  const [choice, setChoice] = useState<OnboardingChoice | null>(null);
  const [copied, setCopied] = useState(false);

  const podman = useApi<{ items: LocalImage[] }>(source === 'local' ? '/podman/images' : null);
  const localImages = useMemo(() => (podman.data?.items ?? []).filter((i) => !i.dangling && i.tags.length), [podman.data]);
  const selectedLocal = localImages.find((i) => i.id === localId);
  const reference = source === 'local' ? selectedLocal?.tags[0] ?? '' : imageRef.trim();

  const go = (i: number) => {
    setStep(i);
    setMaxReached((m) => Math.max(m, i));
    document.getElementById('wizard-panel')?.focus();
  };

  const runInspect = async () => {
    setInspecting(true);
    setInspectError(null);
    setResult(null);
    try {
      if (source === 'local') {
        const r = await get<{ config: InspectResult['config']; risks: Risk[]; size?: number; tags: string[] }>(
          `/podman/images/${encodeURIComponent(localId)}/config`,
        );
        setResult({
          image: reference,
          checks: [
            { id: 'image_format', status: 'ok', params: { image: reference } },
            { id: 'local_present', status: 'ok', params: { image: reference } },
          ],
          config: r.config,
          risks: [{ level: 'medium', code: 'local_only' }, ...r.risks],
          size: r.size,
          source: 'local',
        });
      } else {
        const r = await post<Omit<InspectResult, 'source'>>('/images/inspect', {
          image: reference,
          username: useCreds && username ? username : undefined,
          password: useCreds && password ? password : undefined,
        });
        setResult({ ...r, source: 'registry' });
      }
    } catch (e) {
      setInspectError(e);
    } finally {
      setInspecting(false);
      // Credentials are used for this single verification only.
      setPassword('');
    }
  };

  useEffect(() => {
    if (step === 1 && !result && !inspecting && !inspectError) void runInspect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step]);

  if (!can('workloads.deploy')) {
    return (
      <>
        <PageHeader title={t('title')} />
        <Alert tone="warn">{t('common:permissionDenied')}</Alert>
      </>
    );
  }

  const failed = (result?.checks ?? []).filter((c) => c.status === 'fail' && BLOCKING.has(c.id));
  const authFailed = result?.checks.some((c) => c.id === 'registry_auth' && c.status === 'fail');
  const verified = !!result && failed.length === 0;

  const toDestination = () => {
    setChoice((c) => c ?? suggestDestination(reference, result?.config ?? null));
    go(3);
  };

  const destErrors: Record<string, string> = {};
  if (choice) {
    if (!isDnsLabel(choice.name, 50)) destErrors.name = t('err.name');
    if (!isDnsLabel(choice.namespace)) destErrors.namespace = t('err.namespace');
    if (choice.replicas < 0 || choice.replicas > 50 || !Number.isInteger(choice.replicas)) destErrors.replicas = t('err.replicas');
    if (choice.port !== null && (choice.port < 1 || choice.port > 65535)) destErrors.port = t('err.port');
    if (choice.storage && (!choice.mountPath.startsWith('/') || choice.mountPath === '/')) destErrors.mountPath = t('err.mountPath');
  }

  const continueToDeploy = () => {
    if (!choice) return;
    navigate('/operations/deploy', { state: { prefill: choiceToSpec(choice, result?.config ?? null), from: 'onboarding' } });
  };

  const sourceValid = source === 'registry' ? reference.length > 0 : !!selectedLocal;

  return (
    <>
      <PageHeader
        title={t('title')}
        subtitle={t('subtitle')}
        help={<HelpLink slug="proc-pubblicare-applicazione" />}
      />
      <div className="wizard">
        <WizardSteps steps={STEPS} current={step} maxReached={maxReached} onSelect={go} label={t('stepsLabel')} />
        <Card>
          <div id="wizard-panel" className="wizard-panel" tabIndex={-1} aria-live="polite">
            {step === 0 && (
              <section aria-labelledby="ob-s0">
                <h2 id="ob-s0">{t('source.title')}</h2>
                <p className="explain">{t('source.explain')}</p>
                <div className="choice-grid" role="radiogroup" aria-label={t('source.title')}>
                  <label className="choice">
                    <input type="radio" name="src" checked={source === 'registry'} onChange={() => setSource('registry')} />
                    <span>
                      <span className="title">{t('source.registry')}</span>
                      <span className="desc" style={{ display: 'block' }}>{t('source.registryDesc')}</span>
                    </span>
                  </label>
                  <label className="choice">
                    <input type="radio" name="src" checked={source === 'local'} onChange={() => setSource('local')} />
                    <span>
                      <span className="title">{t('source.local')}</span>
                      <span className="desc" style={{ display: 'block' }}>{t('source.localDesc')}</span>
                    </span>
                  </label>
                </div>
                {source === 'registry' ? (
                  <>
                    <Field label={t('source.reference')} htmlFor="ob-ref" hint={t('source.referenceHint')}>
                      <input
                        id="ob-ref"
                        className="input"
                        value={imageRef}
                        spellCheck={false}
                        placeholder="registry.example.com/team/app:1.4.2"
                        onChange={(e) => {
                          setImageRef(e.target.value);
                          setResult(null);
                          setInspectError(null);
                          setChoice(null);
                          setMaxReached(0);
                        }}
                      />
                    </Field>
                    <label className="checkbox">
                      <input type="checkbox" checked={useCreds} onChange={(e) => setUseCreds(e.target.checked)} />
                      {t('source.useCredentials')}
                    </label>
                    {useCreds && <Credentials t={t} username={username} password={password} setUsername={setUsername} setPassword={setPassword} />}
                  </>
                ) : (
                  <>
                    {podman.isLoading && <Loading />}
                    {podman.error && (
                      <Alert tone="warn" title={t('source.podmanUnavailable')}>
                        <ErrorPanel error={podman.error} onRetry={() => void podman.refetch()} />
                      </Alert>
                    )}
                    {podman.data && localImages.length === 0 && <Alert tone="info">{t('source.noLocal')}</Alert>}
                    {localImages.length > 0 && (
                      <Field label={t('source.localImage')} htmlFor="ob-local">
                        <select
                          id="ob-local"
                          className="input"
                          value={localId}
                          onChange={(e) => {
                            setLocalId(e.target.value);
                            setResult(null);
                            setChoice(null);
                            setMaxReached(0);
                          }}
                        >
                          <option value="">—</option>
                          {localImages.map((i) => (
                            <option key={i.id} value={i.id}>
                              {i.tags[0]} ({formatBytes(i.size)})
                            </option>
                          ))}
                        </select>
                      </Field>
                    )}
                    <Alert tone="info">{t('source.localNote')}</Alert>
                  </>
                )}
              </section>
            )}

            {step === 1 && (
              <section aria-labelledby="ob-s1">
                <h2 id="ob-s1">{t('verify.title')}</h2>
                <p className="explain">{t(source === 'local' ? 'verify.explainLocal' : 'verify.explain', { image: reference })}</p>
                {inspecting && <Loading label={t('verify.running')} />}
                {inspectError ? <ErrorPanel error={inspectError} onRetry={() => void runInspect()} /> : null}
                {result?.demo && <Alert tone="purple" title="DEMO">{t('verify.demo')}</Alert>}
                {result && (
                  <>
                    <CheckList checks={result.checks.map((c) => ({ ...c, params: c.params ?? {} }))} />
                    {failed.length === 0 ? (
                      <Alert tone="ok" title={t('verify.okTitle')}>{t('verify.okText')}</Alert>
                    ) : (
                      <Alert tone="err" title={t('verify.failTitle')}>
                        <ul style={{ margin: 0, paddingLeft: 18 }}>
                          {failed.map((c) => (
                            <li key={c.id}>{t(`fix.${c.id}`, { ...(c.params ?? {}), defaultValue: t('fix.generic') })}</li>
                          ))}
                        </ul>
                        <div style={{ marginTop: 8 }}>
                          <HelpLink slug="imagepullbackoff" label={t('verify.guide')} />
                        </div>
                      </Alert>
                    )}
                    {authFailed && (
                      <Card title={<span className="row"><KeyRound size={16} /> {t('verify.credentialsTitle')}</span>}>
                        <p className="small">{t('verify.credentialsText')}</p>
                        <Credentials t={t} username={username} password={password} setUsername={setUsername} setPassword={setPassword} />
                        <button
                          type="button"
                          className="btn primary"
                          disabled={!username || !password || inspecting}
                          onClick={() => {
                            setUseCreds(true);
                            void runInspect();
                          }}
                        >
                          <RefreshCw size={14} /> {t('verify.retryWithCredentials')}
                        </button>
                      </Card>
                    )}
                    {!authFailed && failed.length > 0 && (
                      <button type="button" className="btn" onClick={() => void runInspect()} disabled={inspecting}>
                        <RefreshCw size={14} /> {t('verify.retry')}
                      </button>
                    )}
                  </>
                )}
              </section>
            )}

            {step === 2 && result && (
              <section aria-labelledby="ob-s2">
                <h2 id="ob-s2">{t('analysis.title')}</h2>
                <p className="explain">{t('analysis.explain')}</p>
                {result.config ? <ConfigView result={result} t={t} /> : <Alert tone="warn">{t('analysis.noConfig')}</Alert>}
                <h3 style={{ marginTop: 18 }}>{t('analysis.risks')}</h3>
                {result.risks.length === 0 ? (
                  <Alert tone="ok">{t('analysis.noRisks')}</Alert>
                ) : (
                  <ul className="risk-list">
                    {result.risks.map((r) => (
                      <li key={r.code}>
                        <Badge tone={LEVEL_TONE[r.level]}>{t(`common:risk.${r.level}`)}</Badge>
                        <div>
                          <strong>{t(`risk.${r.code}.title`, { defaultValue: r.code })}</strong>
                          <div className="small muted">{t(`risk.${r.code}.text`, { ...(r.params ?? {}), volumes: (r.params?.volumes as string[] | undefined)?.join(', '), defaultValue: '' })}</div>
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            )}

            {step === 3 && choice && (
              <section aria-labelledby="ob-s3">
                <h2 id="ob-s3">{t('dest.title')}</h2>
                <p className="explain">{t('dest.explain')}</p>
                <div className="form-grid">
                  <Field label={t('dest.name')} htmlFor="ob-name" hint={t('dest.nameHint')} error={destErrors.name}>
                    <input id="ob-name" className="input" value={choice.name} aria-invalid={!!destErrors.name} onChange={(e) => setChoice({ ...choice, name: e.target.value.toLowerCase() })} />
                  </Field>
                  <Field label={t('common:namespace')} htmlFor="ob-ns" error={destErrors.namespace}>
                    <NamespaceSelect id="ob-ns" value={choice.namespace} allowAll={false} onChange={(ns) => setChoice({ ...choice, namespace: ns })} />
                  </Field>
                  <Field label={t('dest.replicas')} htmlFor="ob-rep" hint={t('dest.replicasHint')} error={destErrors.replicas}>
                    <input id="ob-rep" className="input" type="number" min={0} max={50} value={choice.replicas} onChange={(e) => setChoice({ ...choice, replicas: Number(e.target.value) })} />
                  </Field>
                  <Field
                    label={t('dest.port')}
                    htmlFor="ob-port"
                    hint={result?.config?.exposedPorts?.length ? t('dest.portFromImage', { ports: result.config.exposedPorts.map((p) => p.port).join(', ') }) : t('dest.portNone')}
                    error={destErrors.port}
                  >
                    <input
                      id="ob-port"
                      className="input"
                      type="number"
                      min={1}
                      max={65535}
                      value={choice.port ?? ''}
                      onChange={(e) => setChoice({ ...choice, port: e.target.value ? Number(e.target.value) : null, probe: e.target.value ? choice.probe : 'none' })}
                    />
                  </Field>
                </div>
                <fieldset>
                  <legend>{t('dest.storage')}</legend>
                  <label className="checkbox">
                    <input type="checkbox" checked={choice.storage} onChange={(e) => setChoice({ ...choice, storage: e.target.checked })} />
                    {t('dest.storageEnable')}
                  </label>
                  {result?.config?.volumes?.length ? <p className="small muted">{t('dest.storageFromImage', { volumes: result.config.volumes.join(', ') })}</p> : null}
                  {choice.storage && (
                    <Field label={t('dest.mountPath')} htmlFor="ob-mp" error={destErrors.mountPath}>
                      <input id="ob-mp" className="input" value={choice.mountPath} onChange={(e) => setChoice({ ...choice, mountPath: e.target.value })} />
                    </Field>
                  )}
                </fieldset>
                <fieldset>
                  <legend>{t('dest.health')}</legend>
                  <p className="small muted">{t('dest.healthExplain')}</p>
                  <div className="row">
                    {(['none', 'tcp', 'http'] as const).map((p) => (
                      <label key={p} className="checkbox">
                        <input type="radio" name="probe" checked={choice.probe === p} disabled={p !== 'none' && !choice.port} onChange={() => setChoice({ ...choice, probe: p })} />
                        {t(`dest.probe.${p}`)}
                      </label>
                    ))}
                  </div>
                  {choice.probe === 'http' && (
                    <Field label={t('dest.probePath')} htmlFor="ob-pp">
                      <input id="ob-pp" className="input" value={choice.probePath} onChange={(e) => setChoice({ ...choice, probePath: e.target.value })} />
                    </Field>
                  )}
                </fieldset>
              </section>
            )}

            {step === 4 && choice && (
              <section aria-labelledby="ob-s4">
                <h2 id="ob-s4">{t('summary.title')}</h2>
                <p className="explain">{t('summary.explain')}</p>
                <dl className="summary-grid">
                  <dt>{t('summary.image')}</dt>
                  <dd><code>{reference}</code></dd>
                  {result?.digest && (<><dt>Digest</dt><dd><code>{result.digest.slice(0, 19)}…</code></dd></>)}
                  <dt>{t('summary.verified')}</dt>
                  <dd>{verified ? <Badge tone="ok">{t('summary.verifiedOk')}</Badge> : <Badge tone="warn">{t('summary.notVerified')}</Badge>}</dd>
                  <dt>{t('dest.name')}</dt>
                  <dd>{choice.name}</dd>
                  <dt>{t('common:namespace')}</dt>
                  <dd>{choice.namespace}</dd>
                  <dt>{t('dest.replicas')}</dt>
                  <dd>{choice.replicas}</dd>
                  <dt>{t('dest.port')}</dt>
                  <dd>{choice.port ?? t('common:none')}</dd>
                  <dt>{t('dest.storage')}</dt>
                  <dd>{choice.storage ? choice.mountPath : t('common:none')}</dd>
                  <dt>{t('dest.health')}</dt>
                  <dd>{t(`dest.probe.${choice.probe}`)}{choice.probe === 'http' ? ` ${choice.probePath}` : ''}</dd>
                  <dt>{t('analysis.risks')}</dt>
                  <dd>{result?.risks.length ? result.risks.map((r) => <Badge key={r.code} tone={LEVEL_TONE[r.level]}>{t(`risk.${r.code}.title`, { defaultValue: r.code })}</Badge>) : t('common:none')}</dd>
                </dl>
                <Alert tone="info" title={t('summary.nextTitle')}>{t('summary.nextText')}</Alert>
                <div className="row">
                  <button type="button" className="btn primary" onClick={continueToDeploy}>
                    <Rocket size={16} /> {t('summary.continue')}
                  </button>
                  <button
                    type="button"
                    className="btn"
                    onClick={() => {
                      void navigator.clipboard?.writeText(reference).then(() => setCopied(true));
                    }}
                  >
                    <Copy size={14} /> {copied ? t('common:copied') : t('summary.copy')}
                  </button>
                </div>
              </section>
            )}
          </div>
          <div className="wizard-nav">
            <button type="button" className="btn" disabled={step === 0} onClick={() => go(step - 1)}>
              <ArrowLeft size={14} /> {t('common:back')}
            </button>
            {step === 0 && (
              <button type="button" className="btn primary" disabled={!sourceValid} onClick={() => go(1)}>
                {t('nav.verify')} <ArrowRight size={14} />
              </button>
            )}
            {step === 1 && (
              <button type="button" className="btn primary" disabled={!verified || inspecting} onClick={() => go(2)}>
                {t('common:next')} <ArrowRight size={14} />
              </button>
            )}
            {step === 2 && (
              <button type="button" className="btn primary" onClick={toDestination}>
                {t('common:next')} <ArrowRight size={14} />
              </button>
            )}
            {step === 3 && (
              <button type="button" className="btn primary" disabled={Object.keys(destErrors).length > 0} onClick={() => go(4)}>
                {t('common:next')} <ArrowRight size={14} />
              </button>
            )}
          </div>
        </Card>
      </div>
      {result && result.source === 'registry' && result.risks.some((r) => r.code === 'secret_in_image_env') && (
        <Alert tone="err" title={<span className="row"><ShieldAlert size={16} /> {t('risk.secret_in_image_env.title')}</span>}>
          {t('risk.secret_in_image_env.text')}
        </Alert>
      )}
    </>
  );
}

function Credentials({
  t,
  username,
  password,
  setUsername,
  setPassword,
}: {
  t: (k: string) => string;
  username: string;
  password: string;
  setUsername: (v: string) => void;
  setPassword: (v: string) => void;
}) {
  return (
    <div style={{ marginTop: 10 }}>
      <Alert tone="info">{t('source.credentialsNote')}</Alert>
      <div className="form-grid">
        <Field label={t('source.username')} htmlFor="ob-user">
          <input id="ob-user" className="input" autoComplete="off" value={username} onChange={(e) => setUsername(e.target.value)} />
        </Field>
        <Field label={t('source.password')} htmlFor="ob-pass">
          <input id="ob-pass" className="input" type="password" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} />
        </Field>
      </div>
    </div>
  );
}

function ConfigView({ result, t }: { result: InspectResult; t: (k: string, o?: Record<string, unknown>) => string }) {
  const c = result.config!;
  const list = (v?: string[]) => (v && v.length ? <code>{v.join(' ')}</code> : '—');
  return (
    <div className="grid cols-2">
      <KeyValue
        items={[
          [t('analysis.ports'), c.exposedPorts?.length ? c.exposedPorts.map((p) => <span key={p.port} className="chip">{p.port}/{p.protocol}</span>) : t('analysis.noPorts')],
          [t('analysis.user'), c.runsAsRoot ? <Badge tone="warn">{c.user || 'root'} ({t('analysis.root')})</Badge> : <code>{c.user}</code>],
          [t('analysis.entrypoint'), list(c.entrypoint)],
          [t('analysis.cmd'), list(c.cmd)],
          [t('analysis.workdir'), c.workingDir || '—'],
          [t('analysis.volumes'), c.volumes?.length ? c.volumes.map((v) => <span key={v} className="chip">{v}</span>) : '—'],
          [t('analysis.healthcheck'), list(c.healthcheck ?? undefined)],
        ]}
      />
      <KeyValue
        items={[
          [t('analysis.platform'), result.platforms?.length ? result.platforms.join(', ') : c.os && c.architecture ? `${c.os}/${c.architecture}` : '—'],
          [t('analysis.size'), result.size ? formatBytes(result.size) : '—'],
          [t('analysis.layers'), result.layers ?? '—'],
          [t('analysis.created'), c.created ?? '—'],
          [t('analysis.env'), c.env?.length ? (
            <div>{c.env.map((e) => <div key={e.name} className="mono small">{e.name}={e.value}</div>)}</div>
          ) : '—'],
          [t('analysis.labels'), c.labels && Object.keys(c.labels).length ? Object.entries(c.labels).slice(0, 10).map(([k, v]) => <div key={k} className="mono small ellipsis" title={`${k}=${v}`}>{k}={v}</div>) : '—'],
        ]}
      />
    </div>
  );
}

