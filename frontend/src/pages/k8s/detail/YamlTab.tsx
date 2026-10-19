import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { CheckCircle2, Copy, GitCompare, Pencil, Upload, X } from 'lucide-react';
import { post } from '@/api/client';
import type { ResourceDetail } from '@/api/types';
import { useAuth } from '@/auth/AuthContext';
import { useAction } from '@/hooks/api';
import { YamlDiff, YamlEditor, yamlSyntaxErrors } from '@/components/YamlEditor';
import { ConfirmDialog } from '@/components/Dialog';
import { ErrorPanel } from '@/components/ErrorPanel';
import { Alert, Segmented } from '@/components/ui';
import { useToast } from '@/components/Toasts';

interface ValidateResult {
  valid: boolean;
  serverChecked?: boolean;
  errors: { line?: number; column?: number; message: string; causes?: { field?: string; message?: string }[] | null }[];
}

const WORKLOAD_KINDS = new Set(['Pod', 'Deployment', 'ReplicaSet', 'StatefulSet', 'DaemonSet', 'Job', 'CronJob', 'Service', 'Ingress',
  'PersistentVolumeClaim', 'ConfigMap', 'PodDisruptionBudget', 'HorizontalPodAutoscaler']);

export function YamlTab({ data, onApplied }: { data: ResourceDetail; onApplied: () => void }) {
  const { t } = useTranslation('k8s');
  const { can } = useAuth();
  const toast = useToast();
  const [mode, setMode] = useState<'yaml' | 'json'>('yaml');
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(data.yaml);
  const [validation, setValidation] = useState<ValidateResult | null>(null);
  const [showDiff, setShowDiff] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const editable = data.kind.actions.includes('edit') && (WORKLOAD_KINDS.has(data.kind.kind) ? can('workloads.deploy') : can('resources.apply'));
  const syntax = editing ? yamlSyntaxErrors(draft) : [];
  const changed = draft !== data.yaml;

  const validate = useAction((yaml: string) => post<ValidateResult>('/k8s/validate', { yaml, namespace: data.summary.namespace }), {
    invalidate: false,
    onSuccess: (r) => setValidation(r),
  });
  const apply = useAction((yaml: string) => post<{ ok: boolean; results: { ok: boolean; error?: { message: string } }[] }>('/k8s/apply', { yaml, namespace: data.summary.namespace }), {
    onSuccess: (r) => {
      if (r.ok) {
        toast('ok', t('yaml.applied'));
        setEditing(false);
        setConfirm(false);
        setValidation(null);
        onApplied();
      } else {
        setError(new Error(r.results.map((x) => x.error?.message).filter(Boolean).join('\n')));
      }
    },
  });

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(mode === 'json' ? JSON.stringify(data.object, null, 2) : data.yaml);
      toast('ok', t('common:copied'));
    } catch {
      /* clipboard not available (http) */
    }
  };

  return (
    <div className="stack">
      <div className="row between">
        <div className="row">
          {!editing && (
            <Segmented
              label={t('yaml.yaml')}
              value={mode}
              onChange={setMode}
              options={[
                { value: 'yaml', label: t('yaml.yaml') },
                { value: 'json', label: t('yaml.json') },
              ]}
            />
          )}
          <span className="small muted">{t('yaml.managedFieldsHidden')}</span>
        </div>
        <div className="row">
          {!editing && (
            <button type="button" className="btn sm" onClick={() => void copy()}>
              <Copy size={14} /> {t('common:copy')}
            </button>
          )}
          {!editing && editable && (
            <button type="button" className="btn sm primary" onClick={() => { setDraft(data.yaml); setEditing(true); setValidation(null); setError(null); }}>
              <Pencil size={14} /> {t('yaml.edit')}
            </button>
          )}
          {editing && (
            <>
              <button type="button" className="btn sm" disabled={syntax.length > 0 || validate.busy} onClick={() => void validate.run(draft)}>
                <CheckCircle2 size={14} /> {t('yaml.validate')}
              </button>
              <button type="button" className="btn sm" onClick={() => setShowDiff(!showDiff)} aria-pressed={showDiff}>
                <GitCompare size={14} /> {t('yaml.diff')}
              </button>
              <button type="button" className="btn sm primary" disabled={!changed || syntax.length > 0} onClick={() => setConfirm(true)}>
                <Upload size={14} /> {t('yaml.apply')}
              </button>
              <button type="button" className="btn sm" onClick={() => { setEditing(false); setShowDiff(false); setDraft(data.yaml); }}>
                <X size={14} /> {t('yaml.cancelEdit')}
              </button>
            </>
          )}
        </div>
      </div>
      {!editable && !editing && data.kind.actions.includes('edit') && <p className="small muted">{t('common:readOnlyHint')}</p>}
      {syntax.map((e) => (
        <Alert key={e.line} tone="err">{t('yaml.syntaxError', { line: e.line, message: e.message })}</Alert>
      ))}
      {validation && (
        <Alert tone={validation.valid ? 'ok' : 'err'} title={validation.valid ? (validation.serverChecked ? t('yaml.valid') : t('yaml.validLocal')) : t('yaml.invalid')}>
          {validation.errors.length > 0 && (
            <ul className="small">
              {validation.errors.map((e, i) => (
                <li key={i}>
                  {e.line ? `${t('errors:line')} ${e.line}: ` : ''}
                  {e.message}
                  {e.causes?.map((c, j) => (
                    <div key={j}><code>{c.field}</code> {c.message}</div>
                  ))}
                </li>
              ))}
            </ul>
          )}
        </Alert>
      )}
      {error ? <ErrorPanel error={error} /> : null}
      {editing && showDiff && (changed ? <YamlDiff original={data.yaml} modified={draft} /> : <Alert tone="info">{t('yaml.noChanges')}</Alert>)}
      {editing ? (
        <YamlEditor value={draft} onChange={setDraft} label={`YAML ${data.kind.kind} ${data.summary.name}`} />
      ) : mode === 'json' ? (
        <pre className="code" tabIndex={0}>{JSON.stringify(data.object, null, 2)}</pre>
      ) : (
        <YamlEditor value={data.yaml} readOnly label={`YAML ${data.kind.kind} ${data.summary.name}`} />
      )}
      {confirm && (
        <ConfirmDialog
          spec={{
            title: t('yaml.applyTitle'),
            operation: t('yaml.apply'),
            resource: `${data.kind.kind}/${data.summary.name}`,
            namespace: data.summary.namespace,
            consequences: [t('yaml.applyConsequences')],
            risk: 'medium',
            extra: <div style={{ marginTop: 10 }}><YamlDiff original={data.yaml} modified={draft} /></div>,
          }}
          busy={apply.busy}
          onClose={() => setConfirm(false)}
          onConfirm={() => void apply.run(draft).catch((e) => setError(e))}
        />
      )}
    </div>
  );
}
