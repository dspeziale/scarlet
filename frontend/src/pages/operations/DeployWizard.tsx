import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { Link, useLocation, useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { ArrowLeft, ArrowRight, CheckCircle2, Download, Plus, Rocket, Trash2, XCircle } from 'lucide-react';
import { ApiError, post } from '@/api/client';
import type { ResourceDetail, ResourceList } from '@/api/types';
import { useAuth } from '@/auth/AuthContext';
import { useApi } from '@/hooks/api';
import { Alert, Badge, Card, Field, Loading, PageHeader, Progress, type Tone } from '@/components/ui';
import { ErrorPanel } from '@/components/ErrorPanel';
import { HelpLink } from '@/components/HelpLink';
import { NamespaceSelect } from '@/components/NamespaceSelect';
import { YamlEditor } from '@/components/YamlEditor';
import { WizardSteps } from './WizardSteps';
import {
  DEPLOY_STEPS,
  defaultSpec,
  errorsForStep,
  mapServerErrors,
  mergeSpec,
  splitImage,
  stepOf,
  toPayload,
  validateSpec,
  type DeploySpec,
  type ProbeSpec,
} from './logic';
import '@/styles/pages-b.css';

interface Preview {
  manifests: Record<string, unknown>[];
  yaml: string;
  risks: { level: 'low' | 'medium' | 'high'; code: string; params?: Record<string, unknown> }[];
  blocking: { code: string; params?: Record<string, unknown> }[];
  dryRun: { kind: string; name: string; namespace?: string; ok: boolean; existed: boolean; error?: { code: string; message: string; params?: Record<string, unknown> } }[];
  valid: boolean;
}

interface DeployResult {
  ok: boolean;
  results: { kind: string; name: string; namespace?: string; ok: boolean; existed: boolean; error?: { code: string; message: string } }[];
}

const LEVEL_TONE: Record<string, Tone> = { high: 'err', medium: 'warn', low: 'info' };
const CPU_PRESETS = ['100m', '250m', '500m', '1', '2'];
const MEM_PRESETS = ['128Mi', '256Mi', '512Mi', '1Gi', '2Gi'];
const READY_TIMEOUT_MS = 180_000;

export default function DeployWizard() {
  const { t } = useTranslation('deploy');
  const { can } = useAuth();
  const location = useLocation();
  const [params] = useSearchParams();
  const fromOnboarding = (location.state as { from?: string } | null)?.from === 'onboarding';

  const [spec, setSpec] = useState<DeploySpec>(() => {
    const prefill = (location.state as { prefill?: Partial<DeploySpec> } | null)?.prefill;
    let s = mergeSpec(defaultSpec(), prefill);
    const img = params.get('image');
    if (img && !prefill) {
      const { image, tag } = splitImage(img);
      s = { ...s, image, tag };
    }
    return s;
  });
  const [step, setStep] = useState(0);
  const [maxReached, setMaxReached] = useState(0);
  const [touched, setTouched] = useState<Set<number>>(new Set());
  const [serverErrors, setServerErrors] = useState<Record<string, string>>({});
  const [preview, setPreview] = useState<Preview | null>(null);
  const [previewBusy, setPreviewBusy] = useState(false);
  const [previewError, setPreviewError] = useState<unknown>(null);
  const [deployBusy, setDeployBusy] = useState(false);
  const [deployError, setDeployError] = useState<unknown>(null);
  const [result, setResult] = useState<DeployResult | null>(null);
  const [deployedAt, setDeployedAt] = useState<number | null>(null);

  const STEPS = DEPLOY_STEPS.map((s) => t(`steps.${s}`));
  const errors = useMemo(() => validateSpec(spec), [spec]);
  const stepName = DEPLOY_STEPS[step];
  const stepErrors = errorsForStep(errors, stepName);
  const showErrors = touched.has(step);

  const storageClasses = useApi<ResourceList>(step === 7 ? '/k8s/storageclasses' : null, undefined, { staleTime: 60_000 });
  const watching = deployedAt !== null && result?.ok;
  const watched = useApi<ResourceDetail>(watching ? `/k8s/deployments/${encodeURIComponent(spec.namespace)}/${encodeURIComponent(spec.name)}` : null, undefined, {
    refetchInterval: (q) => {
      const s = q.state.data?.summary;
      const ready = s && Number(s.readyReplicas ?? 0) >= Number(s.replicas ?? 0);
      return ready || (deployedAt && Date.now() - deployedAt > READY_TIMEOUT_MS) ? false : 3000;
    },
  });

  const set = <K extends keyof DeploySpec>(k: K, v: DeploySpec[K]) => {
    setSpec((s) => ({ ...s, [k]: v }));
    setPreview(null);
    setServerErrors((e) => {
      const n = { ...e };
      delete n[k as string];
      return n;
    });
  };

  const err = (field: string): string | undefined => {
    if (serverErrors[field]) return serverErrors[field];
    const code = errors[field];
    return code && (showErrors || touched.has(DEPLOY_STEPS.indexOf(stepOf(field)))) ? t(`err.${code}`) : undefined;
  };

  const go = (i: number) => {
    setStep(i);
    setMaxReached((m) => Math.max(m, i));
    setTimeout(() => document.getElementById('deploy-panel')?.focus(), 0);
  };

  const next = () => {
    setTouched((s) => new Set(s).add(step));
    if (Object.keys(stepErrors).length > 0) return;
    if (step === 9) {
      // Before the summary every earlier step must be valid.
      const firstBad = Object.keys(errors)[0];
      if (firstBad) {
        const idx = DEPLOY_STEPS.indexOf(stepOf(firstBad));
        setTouched((s) => new Set(s).add(idx));
        go(idx);
        return;
      }
    }
    go(step + 1);
  };

  const loadPreview = async () => {
    setPreviewBusy(true);
    setPreviewError(null);
    try {
      setPreview(await post<Preview>('/deploy/preview', toPayload(spec)));
    } catch (e) {
      if (e instanceof ApiError && e.code === 'validation_failed') {
        const mapped = mapServerErrors(e.params.errors as { field?: string; message?: string }[]);
        setServerErrors(mapped);
        const f = Object.keys(mapped)[0];
        if (f) {
          setTouched((s) => new Set(s).add(DEPLOY_STEPS.indexOf(stepOf(f))));
        }
      }
      setPreviewError(e);
    } finally {
      setPreviewBusy(false);
    }
  };

  useEffect(() => {
    if (stepName === 'summary' && !preview && !previewBusy) void loadPreview();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stepName]);

  const doDeploy = async () => {
    setDeployBusy(true);
    setDeployError(null);
    try {
      const r = await post<DeployResult>('/deploy', toPayload(spec));
      setResult(r);
      if (r.ok) setDeployedAt(Date.now());
    } catch (e) {
      setDeployError(e);
    } finally {
      setDeployBusy(false);
    }
  };

  const downloadYaml = () => {
    if (!preview) return;
    const url = URL.createObjectURL(new Blob([preview.yaml], { type: 'application/yaml' }));
    const a = document.createElement('a');
    a.href = url;
    a.download = `${spec.name || 'deploy'}.yaml`;
    a.click();
    URL.revokeObjectURL(url);
  };

  if (!can('workloads.deploy')) {
    return (
      <>
        <PageHeader title={t('title')} />
        <Alert tone="warn">{t('common:permissionDenied')}</Alert>
      </>
    );
  }

  const probe = (which: 'readiness' | 'liveness') => {
    const p = spec[which];
    const upd = (v: Partial<ProbeSpec>) => set(which, { ...p, ...v });
    return (
      <fieldset>
        <legend>{t(`health.${which}`)}</legend>
        <p className="small muted">{t(`health.${which}Explain`)}</p>
        <div className="form-grid">
          <Field label={t('health.type')} htmlFor={`${which}-type`}>
            <select id={`${which}-type`} className="input" value={p.type} onChange={(e) => upd({ type: e.target.value as ProbeSpec['type'] })}>
              <option value="none">{t('health.none')}</option>
              <option value="http" disabled={!spec.port && !p.port}>HTTP</option>
              <option value="tcp" disabled={!spec.port && !p.port}>TCP</option>
            </select>
          </Field>
          {p.type === 'http' && (
            <Field label={t('health.path')} htmlFor={`${which}-path`} error={err(`${which}.path`)}>
              <input id={`${which}-path`} className="input" value={p.path} onChange={(e) => upd({ path: e.target.value })} />
            </Field>
          )}
          {p.type !== 'none' && (
            <>
              <Field label={t('health.port')} htmlFor={`${which}-port`} hint={t('health.portHint', { port: spec.port ?? '—' })} error={err(`${which}.port`)}>
                <input id={`${which}-port`} className="input" type="number" value={p.port ?? ''} onChange={(e) => upd({ port: e.target.value ? Number(e.target.value) : null })} />
              </Field>
              <Field label={t('health.initialDelay')} htmlFor={`${which}-delay`}>
                <input id={`${which}-delay`} className="input" type="number" min={0} max={600} value={p.initial_delay} onChange={(e) => upd({ initial_delay: Number(e.target.value) || 0 })} />
              </Field>
              <Field label={t('health.period')} htmlFor={`${which}-period`}>
                <input id={`${which}-period`} className="input" type="number" min={1} max={300} value={p.period} onChange={(e) => upd({ period: Math.max(1, Number(e.target.value) || 1) })} />
              </Field>
              <Field label={t('health.failureThreshold')} htmlFor={`${which}-fail`}>
                <input id={`${which}-fail`} className="input" type="number" min={1} max={30} value={p.failure_threshold} onChange={(e) => upd({ failure_threshold: Math.max(1, Number(e.target.value) || 1) })} />
              </Field>
            </>
          )}
        </div>
      </fieldset>
    );
  };

  const presets = (values: string[], field: 'cpu_request' | 'cpu_limit' | 'memory_request' | 'memory_limit') => (
    <div className="preset-row" role="group" aria-label={t('presets')}>
      {values.map((v) => (
        <button key={v} type="button" className={`btn sm ${spec[field] === v ? 'primary' : ''}`} onClick={() => set(field, v)}>
          {v}
        </button>
      ))}
      <button type="button" className="btn sm ghost" onClick={() => set(field, null)}>
        {t('none')}
      </button>
    </div>
  );

  let body: ReactNode = null;
  switch (stepName) {
    case 'name':
      body = (
        <>
          <p className="explain">{t('name.explain')}</p>
          <div className="form-grid">
            <Field label={t('name.name')} htmlFor="d-name" hint={t('name.nameHint')} error={err('name')}>
              <input id="d-name" className="input" value={spec.name} aria-invalid={!!err('name')} onChange={(e) => set('name', e.target.value.toLowerCase())} />
            </Field>
            <Field label={t('common:namespace')} htmlFor="d-ns" hint={t('name.nsHint')} error={err('namespace')}>
              {spec.create_namespace ? (
                <input id="d-ns" className="input" value={spec.namespace} onChange={(e) => set('namespace', e.target.value.toLowerCase())} />
              ) : (
                <NamespaceSelect id="d-ns" value={spec.namespace} allowAll={false} onChange={(ns) => set('namespace', ns)} />
              )}
            </Field>
          </div>
          <label className="checkbox">
            <input type="checkbox" checked={spec.create_namespace} disabled={!can('resources.apply')} onChange={(e) => set('create_namespace', e.target.checked)} />
            {t('name.createNs')}
          </label>
          <p className="small muted">{can('resources.apply') ? t('name.createNsHint') : t('name.createNsAdminOnly')}</p>
          <HelpLink slug="namespace" label={t('common:helpWhatIs', { kind: 'Namespace' })} />
        </>
      );
      break;
    case 'image':
      body = (
        <>
          <p className="explain">{t('image.explain')}</p>
          {fromOnboarding && <Alert tone="ok">{t('image.fromOnboarding')}</Alert>}
          <Field label={t('image.image')} htmlFor="d-image" hint={t('image.imageHint')} error={err('image')}>
            <input id="d-image" className="input" value={spec.image} spellCheck={false} placeholder="registry.example.com/team/app" onChange={(e) => set('image', e.target.value)} />
          </Field>
          <Field label={t('image.pullSecret')} htmlFor="d-ps" hint={t('image.pullSecretHint')} error={err('image_pull_secret')}>
            <input id="d-ps" className="input" value={spec.image_pull_secret ?? ''} onChange={(e) => set('image_pull_secret', e.target.value || null)} />
          </Field>
          <p className="small">
            {t('image.notVerified')} <Link to={`/operations/onboarding?image=${encodeURIComponent(spec.image + (spec.tag ? `:${spec.tag}` : ''))}`}>{t('image.goOnboarding')}</Link>
          </p>
        </>
      );
      break;
    case 'tag':
      body = (
        <>
          <p className="explain">{t('tag.explain')}</p>
          <Field label={t('tag.tag')} htmlFor="d-tag" hint={t('tag.tagHint')} error={err('tag')}>
            <input id="d-tag" className="input" value={spec.tag} spellCheck={false} placeholder="1.4.2" onChange={(e) => set('tag', e.target.value)} />
          </Field>
          {spec.tag.trim() === 'latest' && <Alert tone="warn" title={t('tag.latestTitle')}>{t('tag.latestText')}</Alert>}
          <p className="small muted">{t('tag.result', { ref: `${spec.image || '…'}:${spec.tag || '…'}` })}</p>
        </>
      );
      break;
    case 'replicas':
      body = (
        <>
          <p className="explain">{t('replicas.explain')}</p>
          <Field label={t('replicas.replicas')} htmlFor="d-rep" error={err('replicas')}>
            <input id="d-rep" className="input" type="number" min={0} max={50} value={spec.replicas} onChange={(e) => set('replicas', Number(e.target.value))} />
          </Field>
          {spec.replicas === 0 && <Alert tone="warn">{t('replicas.zero')}</Alert>}
          {spec.replicas === 1 && <Alert tone="warn">{t('replicas.one')}</Alert>}
          {spec.replicas >= 2 && <Alert tone="ok">{t('replicas.many', { count: spec.replicas })}</Alert>}
          <HelpLink slug="replica" />
        </>
      );
      break;
    case 'port':
      body = (
        <>
          <p className="explain">{t('port.explain')}</p>
          <div className="form-grid">
            <Field label={t('port.port')} htmlFor="d-port" hint={t('port.portHint')} error={err('port')}>
              <input id="d-port" className="input" type="number" min={1} max={65535} value={spec.port ?? ''} onChange={(e) => set('port', e.target.value ? Number(e.target.value) : null)} />
            </Field>
            <Field label={t('port.protocol')} htmlFor="d-proto">
              <select id="d-proto" className="input" value={spec.protocol} onChange={(e) => set('protocol', e.target.value as 'TCP' | 'UDP')}>
                <option>TCP</option>
                <option>UDP</option>
              </select>
            </Field>
          </div>
          <fieldset>
            <legend>{t('port.env')}</legend>
            <p className="small muted">{t('port.envHint')}</p>
            {spec.env.map((v, i) => (
              <div className="row" key={i} style={{ marginBottom: 6 }}>
                <input className="input sm" aria-label={t('port.envName')} placeholder="NAME" value={v.name} aria-invalid={!!err(`env.${i}`)} onChange={(e) => set('env', spec.env.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)))} />
                <input className="input sm" style={{ flex: 1 }} aria-label={t('port.envValue')} placeholder="value" value={v.value} onChange={(e) => set('env', spec.env.map((x, j) => (j === i ? { ...x, value: e.target.value } : x)))} />
                <button type="button" className="btn sm icon" aria-label={t('common:delete')} onClick={() => set('env', spec.env.filter((_, j) => j !== i))}>
                  <Trash2 size={14} />
                </button>
                {err(`env.${i}`) && <span className="small" style={{ color: 'var(--err)' }}>{err(`env.${i}`)}</span>}
              </div>
            ))}
            {err('env') && <div className="error small" style={{ color: 'var(--err)' }}>{err('env')}</div>}
            <button type="button" className="btn sm" onClick={() => set('env', [...spec.env, { name: '', value: '' }])}>
              <Plus size={14} /> {t('port.addEnv')}
            </button>
          </fieldset>
        </>
      );
      break;
    case 'cpu':
      body = (
        <>
          <p className="explain">{t('cpu.explain')}</p>
          <Field label={t('cpu.request')} htmlFor="d-cpur" hint={t('cpu.requestHint')} error={err('cpu_request')}>
            <input id="d-cpur" className="input" value={spec.cpu_request ?? ''} onChange={(e) => set('cpu_request', e.target.value || null)} />
          </Field>
          {presets(CPU_PRESETS, 'cpu_request')}
          <Field label={t('cpu.limit')} htmlFor="d-cpul" hint={t('cpu.limitHint')} error={err('cpu_limit')}>
            <input id="d-cpul" className="input" value={spec.cpu_limit ?? ''} onChange={(e) => set('cpu_limit', e.target.value || null)} />
          </Field>
          {presets(CPU_PRESETS, 'cpu_limit')}
          <HelpLink slug="resource-request" />
        </>
      );
      break;
    case 'memory':
      body = (
        <>
          <p className="explain">{t('memory.explain')}</p>
          <Field label={t('memory.request')} htmlFor="d-memr" hint={t('memory.requestHint')} error={err('memory_request')}>
            <input id="d-memr" className="input" value={spec.memory_request ?? ''} onChange={(e) => set('memory_request', e.target.value || null)} />
          </Field>
          {presets(MEM_PRESETS, 'memory_request')}
          <Field label={t('memory.limit')} htmlFor="d-meml" hint={t('memory.limitHint')} error={err('memory_limit')}>
            <input id="d-meml" className="input" value={spec.memory_limit ?? ''} onChange={(e) => set('memory_limit', e.target.value || null)} />
          </Field>
          {presets(MEM_PRESETS, 'memory_limit')}
          {!spec.memory_limit && <Alert tone="warn">{t('memory.noLimit')}</Alert>}
          <HelpLink slug="resource-limit" />
        </>
      );
      break;
    case 'storage': {
      const st = spec.storage;
      const upd = (v: Partial<DeploySpec['storage']>) => set('storage', { ...st, ...v });
      body = (
        <>
          <p className="explain">{t('storage.explain')}</p>
          <label className="checkbox">
            <input type="checkbox" checked={st.enabled} onChange={(e) => upd({ enabled: e.target.checked })} />
            {t('storage.enable')}
          </label>
          {st.enabled && (
            <div className="form-grid" style={{ marginTop: 12 }}>
              <Field label={t('storage.size')} htmlFor="d-ss" error={err('storage.size')}>
                <input id="d-ss" className="input" value={st.size} onChange={(e) => upd({ size: e.target.value })} />
              </Field>
              <Field label={t('storage.class')} htmlFor="d-sc" hint={t('storage.classHint')} error={err('storage.storage_class')}>
                <select id="d-sc" className="input" value={st.storage_class ?? ''} onChange={(e) => upd({ storage_class: e.target.value || null })}>
                  <option value="">{t('storage.defaultClass')}</option>
                  {(storageClasses.data?.items ?? []).map((sc) => (
                    <option key={sc.name} value={sc.name}>
                      {sc.name}
                      {sc.default ? ` (${t('storage.isDefault')})` : ''}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label={t('storage.mountPath')} htmlFor="d-mp" error={err('storage.mount_path')}>
                <input id="d-mp" className="input" value={st.mount_path} onChange={(e) => upd({ mount_path: e.target.value })} />
              </Field>
              <Field label={t('storage.accessMode')} htmlFor="d-am" hint={t(`storage.am.${st.access_mode}`)}>
                <select id="d-am" className="input" value={st.access_mode} onChange={(e) => upd({ access_mode: e.target.value as DeploySpec['storage']['access_mode'] })}>
                  <option>ReadWriteOnce</option>
                  <option>ReadWriteOncePod</option>
                  <option>ReadWriteMany</option>
                  <option>ReadOnlyMany</option>
                </select>
              </Field>
            </div>
          )}
          {storageClasses.error && <ErrorPanel error={storageClasses.error} onRetry={() => void storageClasses.refetch()} />}
          {st.enabled && (st.access_mode === 'ReadWriteOnce' || st.access_mode === 'ReadWriteOncePod') && spec.replicas > 1 && (
            <Alert tone="err" title={t('storage.rwoTitle')}>{t('storage.rwoText', { replicas: spec.replicas })}</Alert>
          )}
          <HelpLink slug="persistent-volume-claim" />
        </>
      );
      break;
    }
    case 'networking': {
      const n = spec.networking;
      const upd = (v: Partial<DeploySpec['networking']>) => set('networking', { ...n, ...v });
      const ing = (v: Partial<DeploySpec['networking']['ingress']>) => upd({ ingress: { ...n.ingress, ...v } });
      body = (
        <>
          <p className="explain">{t('net.explain')}</p>
          <div className="choice-grid" role="radiogroup" aria-label={t('net.serviceType')}>
            {(['none', 'ClusterIP', 'NodePort', 'LoadBalancer'] as const).map((st) => (
              <label className="choice" key={st}>
                <input type="radio" name="svc" checked={n.service_type === st} disabled={st !== 'none' && !spec.port} onChange={() => upd({ service_type: st })} />
                <span>
                  <span className="title">{t(`net.type.${st}`)}</span>
                  <span className="desc" style={{ display: 'block' }}>{t(`net.typeDesc.${st}`)}</span>
                </span>
              </label>
            ))}
          </div>
          {err('networking.service_type') && <Alert tone="err">{err('networking.service_type')}</Alert>}
          {n.service_type !== 'none' && (
            <div className="form-grid">
              <Field label={t('net.servicePort')} htmlFor="d-sp" hint={t('net.servicePortHint', { port: spec.port ?? '—' })} error={err('networking.service_port')}>
                <input id="d-sp" className="input" type="number" value={n.service_port ?? ''} onChange={(e) => upd({ service_port: e.target.value ? Number(e.target.value) : null })} />
              </Field>
              {(n.service_type === 'NodePort' || n.service_type === 'LoadBalancer') && (
                <Field label={t('net.nodePort')} htmlFor="d-np" hint={t('net.nodePortHint')} error={err('networking.node_port')}>
                  <input id="d-np" className="input" type="number" value={n.node_port ?? ''} onChange={(e) => upd({ node_port: e.target.value ? Number(e.target.value) : null })} />
                </Field>
              )}
            </div>
          )}
          <fieldset>
            <legend>Ingress</legend>
            <p className="small muted">{t('net.ingressExplain')}</p>
            <label className="checkbox">
              <input type="checkbox" checked={n.ingress.enabled} disabled={n.service_type === 'none'} onChange={(e) => ing({ enabled: e.target.checked })} />
              {t('net.ingressEnable')}
            </label>
            {err('networking.ingress.enabled') && <div className="small" style={{ color: 'var(--err)' }}>{err('networking.ingress.enabled')}</div>}
            {n.ingress.enabled && (
              <div className="form-grid" style={{ marginTop: 10 }}>
                <Field label={t('net.host')} htmlFor="d-host" error={err('networking.ingress.host')}>
                  <input id="d-host" className="input" placeholder="app.example.com" value={n.ingress.host} onChange={(e) => ing({ host: e.target.value })} />
                </Field>
                <Field label={t('net.path')} htmlFor="d-path" error={err('networking.ingress.path')}>
                  <input id="d-path" className="input" value={n.ingress.path} onChange={(e) => ing({ path: e.target.value })} />
                </Field>
                <Field label={t('net.class')} htmlFor="d-ic" hint={t('net.classHint')} error={err('networking.ingress.class_name')}>
                  <input id="d-ic" className="input" value={n.ingress.class_name ?? ''} onChange={(e) => ing({ class_name: e.target.value || null })} />
                </Field>
                <Field label={t('net.tls')} htmlFor="d-tls" hint={t('net.tlsHint')} error={err('networking.ingress.tls_secret')}>
                  <input id="d-tls" className="input" value={n.ingress.tls_secret ?? ''} onChange={(e) => ing({ tls_secret: e.target.value || null })} />
                </Field>
              </div>
            )}
          </fieldset>
          <HelpLink slug="service" />
        </>
      );
      break;
    }
    case 'health':
      body = (
        <>
          <p className="explain">{t('health.explain')}</p>
          {!spec.port && <Alert tone="info">{t('health.noPort')}</Alert>}
          {probe('readiness')}
          {probe('liveness')}
          <div className="row">
            <HelpLink slug="readiness-probe" />
            <HelpLink slug="liveness-probe" />
          </div>
        </>
      );
      break;
    case 'summary':
      body = (
        <>
          <p className="explain">{t('summary.explain')}</p>
          <SummaryText spec={spec} t={t} />
          {previewBusy && <Loading label={t('summary.validating')} />}
          {previewError ? <ErrorPanel error={previewError} onRetry={() => void loadPreview()} /> : null}
          {preview && (
            <>
              {preview.blocking.length > 0 && (
                <Alert tone="err" title={t('summary.blockingTitle')}>
                  <ul style={{ margin: 0, paddingLeft: 18 }}>
                    {preview.blocking.map((b) => (
                      <li key={b.code}>{t(`blocking.${b.code}`, { ...(b.params ?? {}) })}</li>
                    ))}
                  </ul>
                </Alert>
              )}
              <h3>{t('summary.risks')}</h3>
              {preview.risks.length === 0 ? (
                <Alert tone="ok">{t('summary.noRisks')}</Alert>
              ) : (
                <ul className="risk-list" style={{ marginBottom: 14 }}>
                  {preview.risks.map((r) => (
                    <li key={r.code}>
                      <Badge tone={LEVEL_TONE[r.level]}>{t(`common:risk.${r.level}`)}</Badge>
                      <div>
                        <strong>{t(`risk.${r.code}.title`, { defaultValue: r.code })}</strong>
                        <div className="small muted">
                          {t(`risk.${r.code}.text`, {
                            ...(r.params ?? {}),
                            resources: ((r.params?.resources as { kind: string; name: string }[] | undefined) ?? []).map((x) => `${x.kind}/${x.name}`).join(', '),
                            defaultValue: '',
                          })}
                        </div>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
              <h3>{t('summary.dryRun')}</h3>
              {preview.dryRun.length === 0 ? (
                <p className="small muted">{t('summary.dryRunSkipped')}</p>
              ) : (
                <ul className="check-list" style={{ marginBottom: 14 }}>
                  {preview.dryRun.map((r) => (
                    <li key={`${r.kind}/${r.name}`}>
                      {r.ok ? <CheckCircle2 size={16} className="check-ok" aria-hidden="true" /> : <XCircle size={16} className="check-fail" aria-hidden="true" />}
                      <div>
                        <strong>
                          {r.kind}/{r.name}
                        </strong>{' '}
                        <span className="small muted">{r.existed ? t('summary.willUpdate') : t('summary.willCreate')}</span>
                        {r.error && <div className="small" style={{ color: 'var(--err)' }}>{r.error.message}</div>}
                      </div>
                    </li>
                  ))}
                </ul>
              )}
              <div className="row between">
                <h3 style={{ margin: 0 }}>{t('summary.yaml')}</h3>
                <button type="button" className="btn sm" onClick={downloadYaml}>
                  <Download size={14} /> {t('summary.downloadYaml')}
                </button>
              </div>
              <div style={{ marginTop: 8 }}>
                <YamlEditor value={preview.yaml} readOnly label={t('summary.yaml')} />
              </div>
            </>
          )}
        </>
      );
      break;
    case 'deploy': {
      const s = watched.data?.summary;
      const ready = Number(s?.readyReplicas ?? 0);
      const desired = Number(s?.replicas ?? spec.replicas);
      const timedOut = deployedAt !== null && Date.now() - deployedAt > READY_TIMEOUT_MS && ready < desired;
      body = (
        <>
          {!result && (
            <>
              <p className="explain">{t('deploy.explain', { name: spec.name, namespace: spec.namespace })}</p>
              {preview && !preview.valid && <Alert tone="err">{t('deploy.previewInvalid')}</Alert>}
              <button type="button" className="btn primary" disabled={deployBusy || !preview?.valid} onClick={() => void doDeploy()}>
                {deployBusy ? <span className="spinner" aria-hidden="true" /> : <Rocket size={16} />} {t('deploy.button')}
              </button>
            </>
          )}
          {deployError ? <ErrorPanel error={deployError} onRetry={() => void doDeploy()} /> : null}
          {result && (
            <>
              <Alert tone={result.ok ? 'ok' : 'err'} title={result.ok ? t('deploy.applied') : t('deploy.failed')}>
                <ul style={{ margin: 0, paddingLeft: 18 }}>
                  {result.results.map((r) => (
                    <li key={`${r.kind}/${r.name}`}>
                      {r.kind}/{r.name}: {r.ok ? (r.existed ? t('deploy.updated') : t('deploy.created')) : r.error?.message}
                    </li>
                  ))}
                </ul>
                {!result.ok && <p className="small" style={{ marginTop: 8 }}>{t('deploy.failedHint')}</p>}
              </Alert>
              {result.ok && (
                <Card title={t('deploy.rolloutTitle')}>
                  <div aria-live="polite">
                    <div className="row between small">
                      <span>{t('deploy.readyCount', { ready, desired })}</span>
                      {s && <Badge tone={ready >= desired ? 'ok' : 'info'}>{t(`common:health.${s.health}`)}</Badge>}
                    </div>
                    <Progress ratio={desired ? ready / desired : 1} tone={ready >= desired ? 'ok' : 'info'} label={t('deploy.rolloutTitle')} />
                    {ready >= desired && desired > 0 && <p className="small" style={{ marginTop: 8 }}>{t('deploy.ready')}</p>}
                    {timedOut && <Alert tone="warn" title={t('deploy.slowTitle')}>{t('deploy.slowText')}</Alert>}
                    {watched.error && <ErrorPanel error={watched.error} />}
                  </div>
                  <div className="row" style={{ marginTop: 10 }}>
                    <Link className="btn primary" to={`/k8s/deployments/${encodeURIComponent(spec.namespace)}/${encodeURIComponent(spec.name)}`}>
                      {t('deploy.openDeployment')}
                    </Link>
                    <Link className="btn" to={`/operations/rollout?namespace=${encodeURIComponent(spec.namespace)}&name=${encodeURIComponent(spec.name)}`}>
                      {t('deploy.watchRollout')}
                    </Link>
                    <Link className="btn" to="/operations-center">
                      {t('deploy.openCenter')}
                    </Link>
                  </div>
                </Card>
              )}
            </>
          )}
        </>
      );
      break;
    }
  }

  return (
    <>
      <PageHeader title={t('title')} subtitle={t('subtitle')} help={<HelpLink slug="proc-pubblicare-applicazione" />} />
      <div className="wizard">
        <WizardSteps steps={STEPS} current={step} maxReached={result ? step : maxReached} onSelect={(i) => !result && go(i)} label={t('stepsLabel')} />
        <Card>
          <div
            id="deploy-panel"
            className="wizard-panel"
            tabIndex={-1}
            onKeyDown={(e) => {
              if (e.altKey && e.key === 'ArrowRight' && step < 10) next();
              if (e.altKey && e.key === 'ArrowLeft' && step > 0 && !result) go(step - 1);
            }}
          >
            <h2>
              {step + 1}. {STEPS[step]}
            </h2>
            {body}
          </div>
          {showErrors && Object.keys(stepErrors).length > 0 && (
            <div role="alert" className="small" style={{ color: 'var(--err)', marginTop: 8 }}>
              {t('fixErrors')}
            </div>
          )}
          <div className="wizard-nav">
            <button type="button" className="btn" disabled={step === 0 || !!result} onClick={() => go(step - 1)}>
              <ArrowLeft size={14} /> {t('common:back')}
            </button>
            <span className="small muted">{t('keyboardHint')}</span>
            {step < 10 && (
              <button type="button" className="btn primary" onClick={next}>
                {t('common:next')} <ArrowRight size={14} />
              </button>
            )}
            {step === 10 && (
              <button type="button" className="btn primary" disabled={!preview?.valid || previewBusy} onClick={() => go(11)}>
                {t('summary.toDeploy')} <ArrowRight size={14} />
              </button>
            )}
          </div>
        </Card>
      </div>
    </>
  );
}

function SummaryText({ spec, t }: { spec: DeploySpec; t: (k: string, o?: Record<string, unknown>) => string }) {
  const n = spec.networking;
  return (
    <dl className="summary-grid" style={{ marginBottom: 14 }}>
      <dt>{t('summary.what')}</dt>
      <dd>{t('summary.whatText', { name: spec.name, namespace: spec.namespace, replicas: spec.replicas, image: `${spec.image}:${spec.tag}` })}</dd>
      <dt>{t('steps.port')}</dt>
      <dd>{spec.port ? `${spec.port}/${spec.protocol}` : t('none')}</dd>
      <dt>{t('summary.resources')}</dt>
      <dd>
        CPU {spec.cpu_request ?? '—'} / {spec.cpu_limit ?? '∞'} · RAM {spec.memory_request ?? '—'} / {spec.memory_limit ?? '∞'}
      </dd>
      <dt>{t('steps.storage')}</dt>
      <dd>{spec.storage.enabled ? `${spec.storage.size} → ${spec.storage.mount_path} (${spec.storage.storage_class ?? t('storage.defaultClass')})` : t('none')}</dd>
      <dt>{t('steps.networking')}</dt>
      <dd>
        {n.service_type === 'none' ? t('none') : t(`net.type.${n.service_type}`)}
        {n.ingress.enabled ? ` · Ingress ${n.ingress.host}${n.ingress.path}${n.ingress.tls_secret ? ' (TLS)' : ''}` : ''}
      </dd>
      <dt>{t('steps.health')}</dt>
      <dd>
        readiness: {spec.readiness.type} · liveness: {spec.liveness.type}
      </dd>
    </dl>
  );
}
