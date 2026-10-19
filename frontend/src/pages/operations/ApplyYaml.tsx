import { useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { TEMPLATES, templateFor } from './templates';
import { useTranslation } from 'react-i18next';
import { CheckCircle2, FileCheck2, GitCompare, Upload, XCircle } from 'lucide-react';
import { dump, loadAll } from 'js-yaml';
import { ApiError, get, post, resPath } from '@/api/client';
import type { KindInfo, ResourceDetail } from '@/api/types';
import { useAuth } from '@/auth/AuthContext';
import { Alert, Badge, Card, Field, Loading, PageHeader } from '@/components/ui';
import { ErrorPanel } from '@/components/ErrorPanel';
import { HelpLink } from '@/components/HelpLink';
import { ConfirmDialog, Dialog } from '@/components/Dialog';
import { NamespaceSelect } from '@/components/NamespaceSelect';
import { YamlDiff, YamlEditor, yamlSyntaxErrors } from '@/components/YamlEditor';
import { useToast } from '@/components/Toasts';
import { useApi } from '@/hooks/api';
import { KIND_KEY, resourceLink } from '@/utils/links';
import { Link } from 'react-router-dom';
import '@/styles/pages-b.css';


interface DocInfo {
  index: number;
  kind?: string;
  name?: string;
  namespace?: string | null;
  obj: Record<string, unknown>;
}

interface ValidateResult {
  valid: boolean;
  serverChecked?: boolean;
  errors: { line?: number | null; column?: number | null; message: string; document?: number; causes?: { field?: string; message?: string }[] | null }[];
  documents: { kind: string; name: string; namespace?: string; ok?: boolean; existed?: boolean; error?: { message: string } }[];
}

interface ApplyResult {
  ok: boolean;
  dryRun: boolean;
  results: { kind: string; name: string; namespace?: string; ok: boolean; existed: boolean; error?: { code: string; message: string; params?: Record<string, unknown> } }[];
}

const EXAMPLE = `apiVersion: v1
kind: ConfigMap
metadata:
  name: example-config
data:
  LOG_LEVEL: info
`;

const NOISE = ['uid', 'resourceVersion', 'creationTimestamp', 'generation', 'managedFields', 'selfLink'];

function clean(obj: Record<string, unknown>): Record<string, unknown> {
  const o = JSON.parse(JSON.stringify(obj)) as Record<string, unknown>;
  delete o.status;
  const meta = (o.metadata ?? {}) as Record<string, unknown>;
  for (const k of NOISE) delete meta[k];
  const ann = meta.annotations as Record<string, unknown> | undefined;
  if (ann) {
    delete ann['kubectl.kubernetes.io/last-applied-configuration'];
    delete ann['deployment.kubernetes.io/revision'];
    if (!Object.keys(ann).length) delete meta.annotations;
  }
  return o;
}

export default function ApplyYaml() {
  const { t } = useTranslation('operations');
  const { can } = useAuth();
  // Which kinds operators may apply comes from the backend registry (kinds.py: workload=True).
  const kindsQ = useApi<{ items: KindInfo[] }>('/k8s/kinds', undefined, { staleTime: Infinity });
  const workloadKinds = useMemo(() => new Set((kindsQ.data?.items ?? []).filter((k) => k.workload).map((k) => k.kind)), [kindsQ.data]);
  const toast = useToast();
  const [params] = useSearchParams();
  const initialNs = params.get('namespace') || 'default';
  const initialTpl = templateFor(params.get('template'));
  const [text, setText] = useState(() => (initialTpl ? initialTpl.yaml(initialNs) : EXAMPLE));
  const [namespace, setNamespace] = useState(initialNs);
  const [validation, setValidation] = useState<ValidateResult | null>(null);
  const [busy, setBusy] = useState<'validate' | 'diff' | 'apply' | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [diffs, setDiffs] = useState<{ doc: DocInfo; current: string | null; proposed: string }[] | null>(null);
  const [confirm, setConfirm] = useState<'apply' | 'force' | null>(null);
  const [result, setResult] = useState<ApplyResult | null>(null);

  const syntax = useMemo(() => yamlSyntaxErrors(text), [text]);
  const docs = useMemo<DocInfo[]>(() => {
    if (syntax.length) return [];
    try {
      return (loadAll(text) as unknown[])
        .filter((d) => d && typeof d === 'object')
        .map((d, i) => {
          const o = d as Record<string, unknown>;
          const meta = (o.metadata ?? {}) as Record<string, unknown>;
          return { index: i, kind: o.kind as string, name: meta.name as string, namespace: (meta.namespace as string) ?? null, obj: o };
        });
    } catch {
      return [];
    }
  }, [text, syntax]);
  const forbidden = docs.filter((d) => d.kind && !(workloadKinds.has(d.kind) ? can('workloads.deploy') : can('resources.apply')));
  const unknownKinds = docs.filter((d) => !d.kind || !KIND_KEY[d.kind]);
  const canAny = can('workloads.deploy') || can('resources.apply');

  const change = (v: string) => {
    setText(v);
    setValidation(null);
    setDiffs(null);
    setResult(null);
    setError(null);
  };

  const validate = async () => {
    setBusy('validate');
    setError(null);
    try {
      setValidation(await post<ValidateResult>('/k8s/validate', { yaml: text, namespace }));
    } catch (e) {
      setError(e);
    } finally {
      setBusy(null);
    }
  };

  const loadDiffs = async () => {
    setBusy('diff');
    setError(null);
    try {
      const out = [];
      for (const d of docs) {
        const key = d.kind ? KIND_KEY[d.kind] : undefined;
        const proposed = dump(d.obj, { noRefs: true, lineWidth: 120 });
        if (!key || !d.name) {
          out.push({ doc: d, current: null, proposed });
          continue;
        }
        const ns = key === 'nodes' || key === 'namespaces' || key === 'persistentvolumes' || key === 'storageclasses' ? null : d.namespace || namespace;
        try {
          const cur = await get<ResourceDetail>(resPath(key, ns, d.name));
          out.push({ doc: d, current: dump(clean(cur.object), { noRefs: true, lineWidth: 120 }), proposed });
        } catch (e) {
          if (e instanceof ApiError && e.status === 404) out.push({ doc: d, current: null, proposed });
          else throw e;
        }
      }
      setDiffs(out);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(null);
    }
  };

  const apply = async (force: boolean) => {
    setBusy('apply');
    setError(null);
    try {
      const r = await post<ApplyResult>('/k8s/apply', { yaml: text, namespace, force });
      setResult(r);
      setConfirm(null);
      if (r.ok) toast('ok', t('yaml.applied'));
    } catch (e) {
      setError(e);
      setConfirm(null);
    } finally {
      setBusy(null);
    }
  };

  const conflict = result?.results.some((r) => !r.ok && r.error?.code === 'k8s_conflict');

  return (
    <>
      <PageHeader title={t('yaml.title')} subtitle={t('yaml.subtitle')} help={<HelpLink slug="troubleshooting" label={t('yaml.guide')} />} />
      {!canAny && <Alert tone="warn">{t('common:readOnlyHint')}</Alert>}
      <Card>
        <div className="row" style={{ marginBottom: 10 }}>
          <Field label={t('yaml.defaultNs')} htmlFor="ay-ns" hint={t('yaml.defaultNsHint')}>
            <NamespaceSelect id="ay-ns" value={namespace} allowAll={false} onChange={setNamespace} />
          </Field>
          <Field label={t('yaml.template')} htmlFor="ay-tpl" hint={t('yaml.templateHint')}>
            <select
              id="ay-tpl"
              className="input sm"
              value=""
              onChange={(e) => {
                const tpl = templateFor(e.target.value);
                if (tpl) change(tpl.yaml(namespace));
              }}
            >
              <option value="">{t('yaml.templatePick')}</option>
              {TEMPLATES.filter((x) => (x.adminOnly ? can('resources.apply') : can('workloads.deploy'))).map((x) => (
                <option key={x.key} value={x.key}>
                  {x.kind}
                </option>
              ))}
            </select>
          </Field>
        </div>
        {initialTpl && <Alert tone="info" title={t('yaml.templateLoaded', { kind: initialTpl.kind })}>{t('yaml.templateSteps')}</Alert>}
        <YamlEditor value={text} onChange={change} label={t('yaml.editor')} minHeight={320} />
        <div aria-live="polite" style={{ marginTop: 8 }}>
          {syntax.length > 0 ? (
            <Alert tone="err" title={t('yaml.syntaxError')}>
              {syntax.map((s) => (
                <div key={s.line}>{t('yaml.atLine', { line: s.line, message: s.message })}</div>
              ))}
            </Alert>
          ) : (
            <p className="small muted">{t('yaml.docsFound', { count: docs.length })}</p>
          )}
        </div>
        {unknownKinds.length > 0 && <Alert tone="warn">{t('yaml.unknownKinds', { kinds: unknownKinds.map((d) => d.kind ?? '?').join(', ') })}</Alert>}
        {forbidden.length > 0 && <Alert tone="warn">{t('yaml.forbiddenKinds', { kinds: [...new Set(forbidden.map((d) => d.kind))].join(', ') })}</Alert>}
        <div className="row">
          <button className="btn" onClick={() => void validate()} disabled={!!busy || syntax.length > 0 || !docs.length}>
            <FileCheck2 size={14} /> {t('yaml.validate')}
          </button>
          <button className="btn" onClick={() => void loadDiffs()} disabled={!!busy || syntax.length > 0 || !docs.length}>
            <GitCompare size={14} /> {t('yaml.diff')}
          </button>
          <button className="btn primary" onClick={() => setConfirm('apply')} disabled={!!busy || syntax.length > 0 || !docs.length || forbidden.length > 0 || !canAny}>
            <Upload size={14} /> {t('yaml.apply')}
          </button>
          {busy && <Loading label={t(`yaml.busy.${busy}`)} />}
        </div>
      </Card>

      {error ? <ErrorPanel error={error} /> : null}

      {validation && (
        <Card title={t('yaml.validationTitle')}>
          {validation.valid ? (
            <Alert tone="ok">{validation.serverChecked ? t('yaml.validServer') : t('yaml.validLocal')}</Alert>
          ) : (
            <Alert tone="err" title={t('yaml.invalid')}>
              <ul style={{ margin: 0, paddingLeft: 18 }}>
                {validation.errors.map((e, i) => (
                  <li key={i}>
                    {e.document ? `${t('yaml.document')} ${e.document}: ` : ''}
                    {e.line ? `${t('yaml.line')} ${e.line}: ` : ''}
                    {e.message}
                    {e.causes?.map((c, j) => (
                      <div key={j} className="small">
                        <code>{c.field}</code> {c.message}
                      </div>
                    ))}
                  </li>
                ))}
              </ul>
            </Alert>
          )}
          <ul className="check-list">
            {validation.documents.map((d) => (
              <li key={`${d.kind}/${d.name}`}>
                {d.ok === false ? <XCircle size={16} className="check-fail" /> : <CheckCircle2 size={16} className="check-ok" />}
                <span>
                  {d.kind}/{d.name} {d.namespace && <span className="chip">{d.namespace}</span>}{' '}
                  {d.existed !== undefined && <span className="small muted">{d.existed ? t('yaml.update') : t('yaml.create')}</span>}
                  {d.error && <div className="small" style={{ color: 'var(--err)' }}>{d.error.message}</div>}
                </span>
              </li>
            ))}
          </ul>
        </Card>
      )}

      {result && (
        <Card title={t('yaml.resultTitle')}>
          <ul className="check-list">
            {result.results.map((r) => {
              const link = resourceLink(r.kind, r.namespace, r.name);
              return (
                <li key={`${r.kind}/${r.name}`}>
                  {r.ok ? <CheckCircle2 size={16} className="check-ok" /> : <XCircle size={16} className="check-fail" />}
                  <span>
                    {link && r.ok ? <Link to={link}>{r.kind}/{r.name}</Link> : `${r.kind}/${r.name}`}{' '}
                    {r.ok ? <Badge tone="ok">{r.existed ? t('yaml.updated') : t('yaml.created')}</Badge> : <span style={{ color: 'var(--err)' }}>{r.error?.message}</span>}
                  </span>
                </li>
              );
            })}
          </ul>
          {conflict && (
            <Alert tone="warn" title={t('yaml.conflictTitle')}>
              <p>{t('yaml.conflictText')}</p>
              {can('resources.apply') ? (
                <button className="btn danger sm" onClick={() => setConfirm('force')}>
                  {t('yaml.force')}
                </button>
              ) : (
                <p className="small">{t('yaml.forceAdminOnly')}</p>
              )}
            </Alert>
          )}
        </Card>
      )}

      {diffs && (
        <Dialog wide title={t('yaml.diffTitle')} onClose={() => setDiffs(null)}>
          {diffs.map((d) => (
            <section key={d.doc.index} style={{ marginBottom: 16 }}>
              <h3>
                {d.doc.kind}/{d.doc.name}{' '}
                {d.current === null ? <Badge tone="info">{t('yaml.new')}</Badge> : <Badge tone="warn">{t('yaml.changed')}</Badge>}
              </h3>
              {d.current === null ? <YamlEditor value={d.proposed} readOnly label={`${d.doc.kind}/${d.doc.name}`} minHeight={80} /> : <YamlDiff original={d.current} modified={d.proposed} />}
            </section>
          ))}
          <p className="small muted">{t('yaml.diffNote')}</p>
        </Dialog>
      )}

      {confirm && (
        <ConfirmDialog
          spec={{
            title: confirm === 'force' ? t('yaml.forceTitle') : t('yaml.confirmTitle', { count: docs.length }),
            operation: confirm === 'force' ? t('yaml.force') : t('yaml.apply'),
            resource: docs.map((d) => `${d.kind}/${d.name}`).join(', '),
            namespace,
            consequences: confirm === 'force' ? [t('yaml.forceCons1'), t('yaml.forceCons2')] : [t('yaml.cons1'), t('yaml.cons2'), t('yaml.cons3')],
            risk: confirm === 'force' || docs.some((d) => d.kind === 'Namespace' || d.kind === 'Secret' || d.kind === 'PersistentVolume') ? 'high' : 'medium',
            typeToConfirm: confirm === 'force' ? 'force' : undefined,
            confirmLabel: confirm === 'force' ? t('yaml.force') : t('yaml.apply'),
          }}
          busy={busy === 'apply'}
          onClose={() => setConfirm(null)}
          onConfirm={() => void apply(confirm === 'force')}
        />
      )}
    </>
  );
}
