import { Link, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, Check, CheckCircle2, CircleHelp, XCircle } from 'lucide-react';
import { post } from '@/api/client';
import type { Check as CheckT, Issue } from '@/api/types';
import { useAuth } from '@/auth/AuthContext';
import { useAction } from '@/hooks/api';
import { REASON_GUIDE } from '@/guide';
import { formatAge, formatBytes } from '@/utils/format';
import { resourceLink, KIND_KEY } from '@/utils/links';
import { SEVERITY_TONE, SeverityBadge } from './ui';
import { useResourceOps } from './ResourceOps';
import { HelpLink } from './HelpLink';

const CHECK_ICON = {
  ok: <CheckCircle2 size={16} className="check-ok" aria-hidden="true" />,
  fail: <XCircle size={16} className="check-fail" aria-hidden="true" />,
  warn: <AlertTriangle size={16} className="check-warn" aria-hidden="true" />,
  unknown: <CircleHelp size={16} className="check-unknown" aria-hidden="true" />,
};

function fmtParams(p: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(p)) {
    if (Array.isArray(v)) out[k] = v.join(', ') || '—';
    else if ((k === 'requested' || k === 'maxNode') && typeof v === 'number' && v > 1e6) out[k] = formatBytes(v);
    else out[k] = v;
  }
  return out;
}

export function CheckList({ checks, likely }: { checks: CheckT[]; likely?: string | null }) {
  const { t } = useTranslation('diag');
  return (
    <ul className="check-list">
      {checks.map((c) => {
        const text = t(`check.${c.id}.${c.status}`, { ...fmtParams(c.params ?? {}), defaultValue: '' });
        return (
          <li key={c.id}>
            {CHECK_ICON[c.status]}
            <div>
              <strong>{t(`check.${c.id}.label`, { defaultValue: c.id })}</strong>
              <span className="sr-only"> — {t(`checkStatus.${c.status}`)}</span>
              {likely === c.id && <span className="badge tone-err" style={{ marginLeft: 8 }}>{t('likelyCause')}</span>}
              {text && <div className="small muted">{text}</div>}
            </div>
          </li>
        );
      })}
    </ul>
  );
}

export function IssueCard({ issue, compact }: { issue: Issue; compact?: boolean }) {
  const { t } = useTranslation('diag');
  const navigate = useNavigate();
  const { can } = useAuth();
  const ops = useResourceOps();
  const ack = useAction((id: number) => post(`/notifications/${id}/ack`), { success: t('markHandled') });
  const params = { ...issue.facts, available: issue.facts.available, desired: issue.facts.desired, condition: issue.facts.condition };
  const resLink = resourceLink(issue.kind, issue.namespace, issue.name);
  const ownerLink = issue.owner ? resourceLink(issue.owner.kind, issue.namespace, issue.owner.name) : null;
  const causes = t(`reason.${issue.reason}.causes`, { returnObjects: true, defaultValue: [] }) as string[];
  const exitMeaning = issue.facts.exitMeaning as string | undefined;
  const guide = issue.guide ?? REASON_GUIDE[issue.reason] ?? null;
  const podForLogs = issue.kind === 'Pod' ? issue.name : null;

  const doAction = (a: string) => {
    switch (a) {
      case 'view_resource':
        if (resLink) navigate(resLink);
        break;
      case 'view_events':
        if (resLink) navigate(`${resLink}?tab=events`);
        break;
      case 'view_yaml':
      case 'view_config':
        if (resLink) navigate(`${resLink}?tab=yaml`);
        break;
      case 'view_logs':
        if (podForLogs) navigate(`${resLink}?tab=logs${issue.container ? `&container=${encodeURIComponent(issue.container)}` : ''}`);
        else if (ownerLink || resLink) navigate(`${ownerLink ?? resLink}?tab=pods`);
        break;
      case 'view_previous_logs':
        if (resLink) navigate(`${resLink}?tab=logs&previous=1${issue.container ? `&container=${encodeURIComponent(issue.container)}` : ''}`);
        break;
      case 'view_pods':
        if (issue.kind === 'Node') navigate(`/k8s/pods?node=${encodeURIComponent(issue.name)}`);
        else navigate(`${resLink}?tab=pods`);
        break;
      case 'view_metrics':
        if (resLink) navigate(`${resLink}?tab=metrics`);
        break;
      case 'check_registry':
        navigate(`/operations/onboarding?image=${encodeURIComponent(String(issue.facts.image ?? ''))}`);
        break;
      case 'restart': {
        const target = issue.owner && KIND_KEY[issue.owner.kind] && ['Deployment', 'StatefulSet', 'DaemonSet'].includes(issue.owner.kind)
          ? { key: KIND_KEY[issue.owner.kind], kind: issue.owner.kind, name: issue.owner.name, namespace: issue.namespace }
          : { key: KIND_KEY[issue.kind], kind: issue.kind, name: issue.name, namespace: issue.namespace, managed: !!issue.owner };
        ops.open('restart', target);
        break;
      }
      case 'rollback':
        navigate(`/operations/rollout?namespace=${encodeURIComponent(issue.namespace ?? '')}&name=${encodeURIComponent(issue.name)}`);
        break;
      case 'resume':
        ops.open('resume', { key: 'deployments', kind: 'Deployment', name: issue.name, namespace: issue.namespace });
        break;
      case 'cordon':
        ops.open('cordon', { key: 'nodes', kind: 'Node', name: issue.name });
        break;
      case 'uncordon':
        ops.open('uncordon', { key: 'nodes', kind: 'Node', name: issue.name });
        break;
    }
  };

  const allowed = (a: string) => {
    if (a === 'guide') return false;
    if (a === 'restart') return can('workloads.restart');
    if (a === 'resume' || a === 'rollback') return can('workloads.rollout');
    if (a === 'cordon' || a === 'uncordon') return can('nodes.maintain');
    if (a.includes('logs')) return can('logs.read');
    if (a === 'check_registry') return can('workloads.deploy') && !!issue.facts.image;
    return true;
  };

  return (
    <article className={`card issue tone-${SEVERITY_TONE[issue.severity]}`} aria-label={`${issue.severity} ${t(`reason.${issue.reason}.title`, { defaultValue: issue.reason })}`}>
      <div className="card-body">
        <div className="issue-head">
          <SeverityBadge severity={issue.severity} />
          <span className="issue-title">{t(`reason.${issue.reason}.title`, { defaultValue: issue.reason })}</span>
          <span className="muted small">·</span>
          {issue.owner && issue.owner.kind !== issue.kind ? (
            <span className="small">
              {issue.owner.kind.toLowerCase()} {ownerLink ? <Link to={ownerLink}><strong>{issue.owner.name}</strong></Link> : <strong>{issue.owner.name}</strong>}
            </span>
          ) : (
            <span className="small">
              {issue.kind.toLowerCase()} {resLink ? <Link to={resLink}><strong>{issue.name}</strong></Link> : <strong>{issue.name}</strong>}
            </span>
          )}
          {issue.namespace && <span className="chip">{issue.namespace}</span>}
          {issue.since && <span className="small muted" style={{ marginLeft: 'auto' }}>{t('since')} {formatAge(issue.since)}</span>}
        </div>
        {(issue.reason === 'WorkloadUnavailable' || issue.reason === 'WorkloadDegraded') && (
          <div style={{ fontSize: 18, fontWeight: 600, margin: '6px 0' }}>
            {String(issue.facts.available)}/{String(issue.facts.desired)} {t('replicasAvailable')}
          </div>
        )}
        <p style={{ margin: '8px 0 4px' }}>{t(`reason.${issue.reason}.simple`, params)}</p>
        <p className="small" style={{ margin: 0 }}>
          <strong>{t('risk')}:</strong> {t(`reason.${issue.reason}.risk`, params)}
        </p>
        {!compact && (
          <div className="grid cols-2" style={{ marginTop: 12 }}>
            <div>
              {issue.checks.length > 0 ? (
                <>
                  <h3 className="small" style={{ marginBottom: 4 }}>{t('checks')}</h3>
                  <CheckList checks={issue.checks} likely={issue.likely_cause} />
                  {exitMeaning && <p className="small muted">{t(`exitMeaning.${exitMeaning}`)}</p>}
                </>
              ) : (
                causes.length > 0 && (
                  <>
                    <h3 className="small" style={{ marginBottom: 4 }}>{t('possibleCauses')}</h3>
                    <ol className="small" style={{ paddingLeft: 18, margin: 0 }}>
                      {causes.map((c) => <li key={c}>{c}</li>)}
                    </ol>
                  </>
                )
              )}
            </div>
            <div>
              <dl className="kv">
                {issue.owner && <><dt>{t('application')}</dt><dd>{issue.owner.kind}/{issue.owner.name}</dd></>}
                {issue.kind === 'Pod' && <><dt>{t('affectedPods')}</dt><dd>{issue.affected.length > 3 ? `${issue.affected.slice(0, 3).join(', ')} +${issue.affected.length - 3}` : issue.affected.join(', ')}</dd></>}
                {issue.node && <><dt>{t('node')}</dt><dd><Link to={resourceLink('Node', null, issue.node)!}>{issue.node}</Link></dd></>}
                {issue.container && <><dt>{t('container')}</dt><dd>{issue.container}</dd></>}
                {issue.facts.image != null && <><dt>Image</dt><dd><code>{String(issue.facts.image)}</code></dd></>}
                {issue.facts.restarts != null && <><dt>Restart</dt><dd>{String(issue.facts.restarts)}</dd></>}
              </dl>
              {issue.checks.length > 0 && causes.length > 0 && (
                <details className="small" style={{ marginTop: 8 }}>
                  <summary>{t('possibleCauses')}</summary>
                  <ol style={{ paddingLeft: 18 }}>{causes.map((c) => <li key={c}>{c}</li>)}</ol>
                </details>
              )}
              {issue.message && (
                <details className="tech">
                  <summary>{t('technicalMessage')}</summary>
                  <pre>{issue.message}</pre>
                </details>
              )}
            </div>
          </div>
        )}
        <div className="row" style={{ marginTop: 12 }}>
          {issue.actions.filter(allowed).map((a) => (
            <button key={a} type="button" className={`btn sm ${a === 'view_resource' ? 'primary' : ''}`} onClick={() => doAction(a)}>
              {t(`action.${a}`)}
            </button>
          ))}
          <HelpLink slug={guide} label={t('action.guide')} />
          {issue.acknowledged ? (
            <span className="badge tone-info" style={{ marginLeft: 'auto' }}>
              <Check size={12} /> {t('acknowledgedBy', { user: issue.acknowledged.by })}
            </span>
          ) : null}
          {!issue.acknowledged && can('notifications.ack') && compact === undefined && (
            <AckButton issue={issue} onAck={(id) => void ack.run(id)} busy={ack.busy} />
          )}
        </div>
      </div>
      {ops.dialog}
    </article>
  );
}

function AckButton({ issue, onAck, busy }: { issue: Issue; onAck: (id: number) => void; busy: boolean }) {
  const { t } = useTranslation('diag');
  const notifId = issue.notificationId;
  if (!notifId) return null;
  return (
    <button type="button" className="btn sm" style={{ marginLeft: 'auto' }} onClick={() => onAck(notifId)} disabled={busy}>
      <Check size={14} /> {t('markHandled')}
    </button>
  );
}
