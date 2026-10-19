import { useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { ApiError, del, post, resPath } from '@/api/client';
import { useAction } from '@/hooks/api';
import { ConfirmDialog, Dialog, type ConfirmSpec } from './Dialog';
import { ErrorPanel } from './ErrorPanel';
import { Field } from './ui';

export type OpKind =
  | 'restart'
  | 'scale'
  | 'pause'
  | 'resume'
  | 'delete'
  | 'rollback'
  | 'cordon'
  | 'uncordon'
  | 'suspend'
  | 'unsuspend'
  | 'trigger';

export interface OpTarget {
  key: string; // kind key (deployments, pods...)
  kind: string; // Deployment, Pod...
  name: string;
  namespace?: string | null;
  replicas?: number;
  revision?: number;
  /** For pods: whether a controller recreates it. */
  managed?: boolean;
}

const HIGH_RISK_DELETE = new Set(['namespaces', 'persistentvolumes', 'persistentvolumeclaims', 'secrets', 'nodes']);

/**
 * Hook returning `open(op, target)` and the dialog element to render.
 * Every state-changing operation is explained (consequences, downtime, risk) before running.
 */
export function useResourceOps(onDone?: (op: OpKind, target: OpTarget) => void): { open: (op: OpKind, target: OpTarget) => void; dialog: ReactNode } {
  const { t } = useTranslation('ops');
  const navigate = useNavigate();
  const [state, setState] = useState<{ op: OpKind; target: OpTarget } | null>(null);
  const [replicas, setReplicas] = useState(1);
  const [error, setError] = useState<unknown>(null);

  const action = useAction(
    async ({ op, target, typed }: { op: OpKind; target: OpTarget; typed: string }) => {
      const base = resPath(target.key, target.namespace, target.name);
      switch (op) {
        case 'restart':
          return post(`${base}/restart`, { confirm: typed || undefined });
        case 'scale':
          return post(`${base}/scale`, { replicas, confirm: typed || undefined });
        case 'pause':
          return post(`${base}/pause`);
        case 'resume':
          return post(`${base}/resume`);
        case 'rollback':
          return post(`${base}/rollback`, { revision: target.revision ?? null });
        case 'cordon':
          return post(`${base}/cordon`);
        case 'uncordon':
          return post(`${base}/uncordon`);
        case 'suspend':
          return post(`${base}/suspend`, { suspend: true });
        case 'unsuspend':
          return post(`${base}/suspend`, { suspend: false });
        case 'trigger':
          return post(`${base}/trigger`);
        case 'delete':
          return del(base, { confirm: typed || undefined });
      }
    },
    {
      success: () => t(`done.${state?.op}`, { name: state?.target.name }),
      onSuccess: () => {
        const s = state;
        setState(null);
        if (s?.op === 'delete' && s.target.key !== 'pods') navigate(`/k8s/${s.target.key}`);
        if (s) onDone?.(s.op, s.target);
      },
    },
  );

  const open = (op: OpKind, target: OpTarget) => {
    setError(null);
    setReplicas(target.replicas ?? 1);
    setState({ op, target });
  };

  let dialog: ReactNode = null;
  if (state) {
    const { op, target } = state;
    const p = { kind: target.kind, name: target.name, from: target.replicas, to: replicas, revision: target.revision ?? t('previousRevision') };
    const unmanagedPod = target.key === 'pods' && target.managed === false;
    let risk: ConfirmSpec['risk'] = 'medium';
    let typeToConfirm: string | undefined;
    if (op === 'delete') {
      risk = HIGH_RISK_DELETE.has(target.key) || unmanagedPod ? 'high' : 'medium';
      typeToConfirm = target.key === 'pods' && !unmanagedPod ? undefined : target.name;
    } else if (op === 'scale' && replicas === 0) {
      risk = 'high';
      typeToConfirm = target.name;
    } else if (op === 'restart' && unmanagedPod) {
      risk = 'high';
      typeToConfirm = target.name;
    } else if (['pause', 'resume', 'uncordon', 'unsuspend', 'trigger'].includes(op)) {
      risk = 'low';
    } else if (op === 'scale' && replicas >= (target.replicas ?? 0)) {
      risk = 'low';
    }
    const consKey = op === 'restart' && target.key === 'pods' ? (unmanagedPod ? 'restartPodUnmanaged' : 'restartPod') : op === 'scale' && replicas === 0 ? 'scaleZero' : op === 'scale' && replicas < (target.replicas ?? 0) ? 'scaleDown' : op === 'scale' ? 'scaleUp' : op === 'delete' ? `delete_${target.key}` : op;
    const consequences = (t(`consequences.${consKey}`, { returnObjects: true, defaultValue: t(`consequences.${op}`, { returnObjects: true, ...p }), ...p }) as unknown) as string[];
    const spec: ConfirmSpec = {
      title: t(`title.${op}`, p),
      operation: t(`label.${op}`, p),
      resource: `${target.kind}/${target.name}`,
      namespace: target.namespace,
      consequences: Array.isArray(consequences) ? consequences : [String(consequences)],
      downtime: t(`downtime.${consKey}`, { defaultValue: t(`downtime.${op}`, { defaultValue: '' }) }) || undefined,
      risk,
      typeToConfirm,
      confirmLabel: t(`label.${op}`, p),
      danger: op === 'delete' || risk === 'high',
      extra:
        op === 'scale' ? (
          <div style={{ marginTop: 12 }}>
            <Field label={t('replicasLabel')} htmlFor="scale-replicas" hint={t('replicasHint', { current: target.replicas })}>
              <input
                id="scale-replicas"
                className="input"
                type="number"
                min={0}
                max={500}
                value={replicas}
                data-autofocus
                onChange={(e) => setReplicas(Math.max(0, Math.min(500, Number(e.target.value) || 0)))}
              />
            </Field>
          </div>
        ) : undefined,
    };
    dialog = (
      <ConfirmDialog
        key={`${op}-${replicas === 0 ? 'zero' : 'n'}`}
        spec={spec}
        busy={action.busy}
        onClose={() => setState(null)}
        error={error ? <div style={{ marginTop: 12 }}><ErrorPanel error={error} /></div> : null}
        onConfirm={(typed) => {
          setError(null);
          action.run({ op, target, typed }).catch((e) => {
            if (e instanceof ApiError && e.code === 'confirmation_required') {
              setError(e);
            } else setError(e);
          });
        }}
      />
    );
  }
  return { open, dialog };
}

/** Simple info dialog helper for read-only explanations. */
export function InfoDialog({ title, children, onClose }: { title: string; children: ReactNode; onClose: () => void }) {
  const { t } = useTranslation();
  return (
    <Dialog title={title} onClose={onClose} footer={<button className="btn" onClick={onClose}>{t('close')}</button>}>
      {children}
    </Dialog>
  );
}
