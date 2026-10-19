import { useId, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { AlertTriangle, CheckCircle2, CircleHelp, Info, OctagonAlert, XCircle } from 'lucide-react';
import type { Health, Severity } from '@/api/types';
import { classNames } from '@/utils/format';

export type Tone = 'ok' | 'warn' | 'err' | 'crit' | 'info' | 'muted' | 'purple';

export const HEALTH_TONE: Record<Health, Tone> = {
  healthy: 'ok',
  completed: 'ok',
  progressing: 'info',
  pending: 'warn',
  degraded: 'warn',
  suspended: 'muted',
  failed: 'err',
  unknown: 'muted',
};

export const SEVERITY_TONE: Record<Severity, Tone> = {
  CRITICAL: 'crit',
  ERROR: 'err',
  WARNING: 'warn',
  INFO: 'info',
};

export function Badge({ tone = 'muted', children, dot, title }: { tone?: Tone; children: ReactNode; dot?: boolean; title?: string }) {
  return (
    <span className={`badge tone-${tone}`} title={title}>
      {dot && <span className="dot" aria-hidden="true" />}
      {children}
    </span>
  );
}

export function HealthBadge({ health, label }: { health: Health; label?: string }) {
  const { t } = useTranslation();
  return (
    <Badge tone={HEALTH_TONE[health] ?? 'muted'} dot>
      {label ?? t(`health.${health}`)}
    </Badge>
  );
}

export function SeverityBadge({ severity }: { severity: Severity }) {
  const { t } = useTranslation();
  return (
    <span className={`badge sev tone-${SEVERITY_TONE[severity]}`} title={t(`severityHelp.${severity}`)}>
      {severity}
    </span>
  );
}

export function Card({
  title,
  actions,
  children,
  flush,
  className,
  id,
}: {
  title?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  flush?: boolean;
  className?: string;
  id?: string;
}) {
  const hid = useId();
  return (
    <section className={classNames('card', className)} aria-labelledby={title ? hid : undefined} id={id}>
      {(title || actions) && (
        <div className="card-header">
          {title && <h2 id={hid}>{title}</h2>}
          {actions && <div className="actions">{actions}</div>}
        </div>
      )}
      <div className={classNames('card-body', flush && 'flush')}>{children}</div>
    </section>
  );
}

export function StatCard({
  label,
  value,
  sub,
  to,
  tone,
  icon,
}: {
  label: ReactNode;
  value: ReactNode;
  sub?: ReactNode;
  to?: string;
  tone?: Tone;
  icon?: ReactNode;
}) {
  const body = (
    <>
      <div className="label">
        {icon}
        {label}
      </div>
      <div className="value">{value}</div>
      {sub && <div className="sub">{sub}</div>}
    </>
  );
  const cls = classNames('card stat', tone && `tone-${tone}`, to && 'clickable');
  return to ? (
    <Link to={to} className={cls}>
      {body}
    </Link>
  ) : (
    <div className={cls}>{body}</div>
  );
}

export function Loading({ label }: { label?: string }) {
  const { t } = useTranslation();
  return (
    <div className="loading" role="status" aria-live="polite">
      <span className="spinner" aria-hidden="true" />
      {label ?? t('loading')}
    </div>
  );
}

export function Empty({ children, icon }: { children: ReactNode; icon?: ReactNode }) {
  return (
    <div className="empty">
      {icon}
      <div>{children}</div>
    </div>
  );
}

const ALERT_ICONS: Record<Tone, ReactNode> = {
  ok: <CheckCircle2 size={18} />,
  warn: <AlertTriangle size={18} />,
  err: <XCircle size={18} />,
  crit: <OctagonAlert size={18} />,
  info: <Info size={18} />,
  muted: <CircleHelp size={18} />,
  purple: <Info size={18} />,
};

export function Alert({ tone = 'info', title, children, role }: { tone?: Tone; title?: ReactNode; children?: ReactNode; role?: string }) {
  return (
    <div className={`alert tone-${tone}`} role={role ?? (tone === 'err' || tone === 'crit' ? 'alert' : 'status')}>
      {ALERT_ICONS[tone]}
      <div className="alert-body">
        {title && <div className="alert-title">{title}</div>}
        {children}
      </div>
    </div>
  );
}

export function KeyValue({ items }: { items: [ReactNode, ReactNode][] }) {
  return (
    <dl className="kv">
      {items.map(([k, v], i) => (
        <div key={i} style={{ display: 'contents' }}>
          <dt>{k}</dt>
          <dd>{v ?? '—'}</dd>
        </div>
      ))}
    </dl>
  );
}

export interface TabDef {
  id: string;
  label: ReactNode;
  hidden?: boolean;
}

export function Tabs({ tabs, value, onChange, label }: { tabs: TabDef[]; value: string; onChange: (id: string) => void; label: string }) {
  const visible = tabs.filter((t) => !t.hidden);
  return (
    <div className="tabs" role="tablist" aria-label={label}>
      {visible.map((t, idx) => (
        <button
          key={t.id}
          role="tab"
          id={`tab-${t.id}`}
          aria-selected={value === t.id}
          aria-controls={`panel-${t.id}`}
          tabIndex={value === t.id ? 0 : -1}
          onClick={() => onChange(t.id)}
          onKeyDown={(e) => {
            if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
              const next = visible[(idx + (e.key === 'ArrowRight' ? 1 : visible.length - 1)) % visible.length];
              onChange(next.id);
              document.getElementById(`tab-${next.id}`)?.focus();
            }
          }}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}

export function TabPanel({ id, children }: { id: string; children: ReactNode }) {
  return (
    <div role="tabpanel" id={`panel-${id}`} aria-labelledby={`tab-${id}`}>
      {children}
    </div>
  );
}

export function Progress({ ratio, tone, label }: { ratio: number | null | undefined; tone?: Tone; label: string }) {
  const pct = ratio === null || ratio === undefined || !Number.isFinite(ratio) ? 0 : Math.min(100, Math.max(0, ratio * 100));
  const autoTone: Tone = tone ?? (pct >= 90 ? 'err' : pct >= 75 ? 'warn' : 'ok');
  return (
    <div className={`progress tone-${autoTone}`} role="progressbar" aria-label={label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(pct)}>
      <span style={{ width: `${pct}%` }} />
    </div>
  );
}

export function PageHeader({
  title,
  subtitle,
  actions,
  breadcrumbs,
  help,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  breadcrumbs?: ReactNode;
  help?: ReactNode;
}) {
  return (
    <header className="page-header">
      <div className="titles">
        {breadcrumbs && <nav className="breadcrumbs" aria-label="breadcrumb">{breadcrumbs}</nav>}
        <h1>{title}</h1>
        {subtitle && <p className="subtitle">{subtitle}</p>}
        {help}
      </div>
      {actions && <div className="actions">{actions}</div>}
    </header>
  );
}

export function Field({
  label,
  hint,
  error,
  children,
  htmlFor,
}: {
  label: ReactNode;
  hint?: ReactNode;
  error?: ReactNode;
  children: ReactNode;
  htmlFor?: string;
}) {
  return (
    <div className="field">
      <label htmlFor={htmlFor}>{label}</label>
      {children}
      {hint && !error && <div className="hint">{hint}</div>}
      {error && (
        <div className="error" role="alert">
          {error}
        </div>
      )}
    </div>
  );
}

export function Segmented<T extends string>({
  options,
  value,
  onChange,
  label,
}: {
  options: { value: T; label: ReactNode }[];
  value: T;
  onChange: (v: T) => void;
  label: string;
}) {
  return (
    <div className="segmented" role="group" aria-label={label}>
      {options.map((o) => (
        <button key={o.value} type="button" aria-pressed={value === o.value} onClick={() => onChange(o.value)}>
          {o.label}
        </button>
      ))}
    </div>
  );
}
