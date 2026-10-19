import { useTranslation } from 'react-i18next';
import { RotateCw } from 'lucide-react';
import { useAuth } from '@/auth/AuthContext';
import { Alert, PageHeader } from '@/components/ui';
import { HelpLink } from '@/components/HelpLink';
import { useResourceOps } from '@/components/ResourceOps';
import { WorkloadPicker } from './WorkloadPicker';
import '@/styles/pages-b.css';

export default function Restart() {
  const { t } = useTranslation('operations');
  const { can } = useAuth();
  const ops = useResourceOps();
  return (
    <>
      <PageHeader title={t('restart.title')} subtitle={t('restart.subtitle')} help={<HelpLink slug="rolling-update" />} />
      <Alert tone="info" title={t('restart.howTitle')}>
        <p>{t('restart.how1')}</p>
        <p>{t('restart.how2')}</p>
      </Alert>
      {!can('workloads.restart') && <Alert tone="warn">{t('common:readOnlyHint')}</Alert>}
      <WorkloadPicker
        kinds={['deployments', 'statefulsets', 'daemonsets']}
        action={(r) =>
          can('workloads.restart') ? (
            <button type="button" className="btn sm" onClick={() => ops.open('restart', { key: r.key, kind: r.kind, name: r.name, namespace: r.namespace })}>
              <RotateCw size={14} /> {t('restart.action')}
            </button>
          ) : null
        }
      />
      {ops.dialog}
    </>
  );
}
