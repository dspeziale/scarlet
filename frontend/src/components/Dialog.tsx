import { useEffect, useId, useRef, useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, X } from 'lucide-react';
import { KeyValue } from './ui';

/** Modal dialog with focus trap, Escape to close and focus restoration. */
export function Dialog({
  title,
  onClose,
  children,
  footer,
  wide,
  className,
}: {
  title: ReactNode;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  wide?: boolean;
  className?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const { t } = useTranslation();
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const node = ref.current;
    const focusables = () =>
      Array.from(node?.querySelectorAll<HTMLElement>('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])') ?? []).filter(
        (el) => !el.hasAttribute('disabled'),
      );
    (node?.querySelector<HTMLElement>('[data-autofocus]') ?? focusables()[0])?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation();
        onClose();
      }
      if (e.key === 'Tab') {
        const els = focusables();
        if (!els.length) return;
        const first = els[0];
        const last = els[els.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener('keydown', onKey, true);
    return () => {
      document.removeEventListener('keydown', onKey, true);
      previous?.focus?.();
    };
  }, [onClose]);
  return createPortal(
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div ref={ref} className={`dialog ${wide ? 'wide' : ''} ${className ?? ''}`} role="dialog" aria-modal="true" aria-labelledby={titleId}>
        <div className="dialog-header">
          <h2 id={titleId}>{title}</h2>
          <button type="button" className="btn ghost icon" style={{ marginLeft: 'auto' }} onClick={onClose} aria-label={t('close')}>
            <X size={18} />
          </button>
        </div>
        <div className="dialog-body">{children}</div>
        {footer && <div className="dialog-footer">{footer}</div>}
      </div>
    </div>,
    document.body,
  );
}

export interface ConfirmSpec {
  title: string;
  operation: string;
  resource: string;
  namespace?: string | null;
  consequences: string[];
  downtime?: string;
  risk: 'low' | 'medium' | 'high';
  /** When set, the user must type this exact value to confirm. */
  typeToConfirm?: string;
  confirmLabel?: string;
  danger?: boolean;
  extra?: ReactNode;
}

/**
 * Confirmation for operations that modify or destroy something: shows what is affected,
 * the consequences, possible downtime and the risk before the user decides.
 */
export function ConfirmDialog({
  spec,
  onConfirm,
  onClose,
  busy,
  error,
}: {
  spec: ConfirmSpec;
  onConfirm: (typed: string) => void;
  onClose: () => void;
  busy?: boolean;
  error?: ReactNode;
}) {
  const { t } = useTranslation();
  const [typed, setTyped] = useState('');
  const inputId = useId();
  const ok = !spec.typeToConfirm || typed === spec.typeToConfirm;
  return (
    <Dialog
      title={spec.title}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose} disabled={busy}>
            {t('cancel')}
          </button>
          <button
            type="button"
            className={`btn ${spec.danger || spec.risk === 'high' ? 'danger' : 'primary'}`}
            disabled={!ok || busy}
            onClick={() => onConfirm(typed)}
          >
            {busy && <span className="spinner" aria-hidden="true" />}
            {spec.confirmLabel ?? t('confirm')}
          </button>
        </>
      }
    >
      <KeyValue
        items={[
          [t('confirmDialog.operation'), <strong key="op">{spec.operation}</strong>],
          [t('confirmDialog.resource'), <code key="r">{spec.resource}</code>],
          ...(spec.namespace ? ([[t('namespace'), <code key="ns">{spec.namespace}</code>]] as [ReactNode, ReactNode][]) : []),
          [
            t('confirmDialog.risk'),
            <span key="risk" className={`badge tone-${spec.risk === 'high' ? 'err' : spec.risk === 'medium' ? 'warn' : 'ok'}`}>
              {t(`risk.${spec.risk}`)}
            </span>,
          ],
          ...(spec.downtime ? ([[t('confirmDialog.downtime'), spec.downtime]] as [ReactNode, ReactNode][]) : []),
        ]}
      />
      {spec.consequences.length > 0 && (
        <div style={{ marginTop: 14 }}>
          <div className="row" style={{ fontWeight: 600 }}>
            <AlertTriangle size={16} className="check-warn" /> {t('confirmDialog.consequences')}
          </div>
          <ul>
            {spec.consequences.map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ul>
        </div>
      )}
      {spec.extra}
      {spec.typeToConfirm && (
        <div className="field" style={{ marginTop: 10 }}>
          <label htmlFor={inputId}>{t('confirmDialog.typeToConfirm', { value: spec.typeToConfirm })}</label>
          <input
            id={inputId}
            className="input"
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
            autoComplete="off"
            spellCheck={false}
            data-autofocus
          />
        </div>
      )}
      {error}
    </Dialog>
  );
}
