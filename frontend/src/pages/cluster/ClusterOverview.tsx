import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import type { Overview, SystemStatus } from '@/api/types';
import { useApi, useSystemStatus } from '@/hooks/api';
import { ErrorPanel } from '@/components/ErrorPanel';
import { HelpLink } from '@/components/HelpLink';
import { Alert, Card, KeyValue, Loading, PageHeader, StatCard } from '@/components/ui';

export default function ClusterOverview() {
  const { t } = useTranslation(['k8s', 'nav', 'dashboard']);
  const status = useSystemStatus();
  const ov = useApi<Overview>('/cluster/overview');
  const k: SystemStatus['kubernetes'] | undefined = status.data?.kubernetes;

  return (
    <>
      <PageHeader title={t('overview.title')} subtitle={t('kinds.Node.simple')} help={<HelpLink slug="cluster" />} />
      <div className="grid cols-2 section">
        <Card title={t('overview.connection')}>
          {status.isLoading && <Loading />}
          {k && (
            <>
              {!k.connected && <Alert tone="err" title={t('overview.notConnected')}>{k.error?.message}</Alert>}
              <KeyValue
                items={[
                  [t('overview.connection'), k.connected ? <span className="badge tone-ok">LIVE</span> : <span className="badge tone-err">offline</span>],
                  [t('overview.context'), k.context ?? '—'],
                  [t('overview.server'), <code key="s">{k.server ?? '—'}</code>],
                  [t('overview.version'), k.version ?? '—'],
                  ['Mode', status.data?.mode.toUpperCase()],
                ]}
              />
              <p style={{ marginTop: 10 }}>
                <Link to="/settings/kubernetes">{t('nav:setKubernetes')}</Link> · <Link to="/monitoring/health">{t('nav:health')}</Link>
              </p>
            </>
          )}
        </Card>
        <Card title={t('dashboard:clusterState')}>
          {ov.error && <ErrorPanel error={ov.error} onRetry={() => void ov.refetch()} />}
          {ov.data && (
            <div className="grid cols-2">
              <StatCard to="/k8s/nodes" label={t('nav:nodes')} value={`${ov.data.nodes.ready}/${ov.data.nodes.total}`} tone={ov.data.nodes.notReady ? 'err' : 'ok'} />
              <StatCard to="/k8s/namespaces" label={t('nav:namespaces')} value={ov.data.namespaces} />
              <StatCard to="/k8s/events" label={t('dashboard:warnings')} value={ov.data.events.warnings} tone={ov.data.events.warnings ? 'warn' : 'ok'} />
              <StatCard to="/operations-center" label={t('nav:operationsCenter')} value={ov.data.issues.counts.CRITICAL + ov.data.issues.counts.ERROR + ov.data.issues.counts.WARNING} />
            </div>
          )}
        </Card>
      </div>
      {ov.data && (
        <Card title={t('overview.kindsTitle')}>
          <div className="grid cols-6">
            <StatCard to="/k8s/pods" label={t('nav:pods')} value={ov.data.pods.total} />
            <StatCard to="/k8s/deployments" label={t('nav:deployments')} value={ov.data.deployments.total} />
            <StatCard to="/k8s/statefulsets" label={t('nav:statefulsets')} value={ov.data.statefulsets.total} />
            <StatCard to="/k8s/daemonsets" label={t('nav:daemonsets')} value={ov.data.daemonsets.total} />
            <StatCard to="/k8s/services" label={t('nav:services')} value={ov.data.services} />
            <StatCard to="/k8s/persistentvolumeclaims" label="PVC" value={ov.data.storage.pvcTotal} />
          </div>
        </Card>
      )}
    </>
  );
}
