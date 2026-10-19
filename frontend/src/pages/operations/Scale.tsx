import { useTranslation } from 'react-i18next';
import { Scaling } from 'lucide-react';
import type { ResourceList } from '@/api/types';
import { useAuth } from '@/auth/AuthContext';
import { useApi } from '@/hooks/api';
import { Alert, Badge, PageHeader } from '@/components/ui';
import { HelpLink } from '@/components/HelpLink';
import { useResourceOps } from '@/components/ResourceOps';
import { WorkloadPicker } from './WorkloadPicker';
import '@/styles/pages-b.css';

export default function Scale() {
  const { t } = useTranslation('operations');
  const { can } = useAuth();
  const ops = useResourceOps();
  // HPAs may not be readable/supported: in that case the column simply shows nothing.
  const hpas = useApi<ResourceList>('/k8s/horizontalpodautoscalers', undefined, { retry: false });
  const hpaFor = (kind: string, ns: string | null, name: string) =>
    (hpas.data?.items ?? []).find((h) => h.namespace === ns && h.target === `${kind}/${name}`);

  return (
    <>
      <PageHeader title={t('scale.title')} subtitle={t('scale.subtitle')} help={<HelpLink slug="proc-scalare" />} />
      <Alert tone="info" title={t('scale.howTitle')}>
        <p>{t('scale.how1')}</p>
        <p>{t('scale.how2')}</p>
      </Alert>
      {!can('workloads.scale') && <Alert tone="warn">{t('common:readOnlyHint')}</Alert>}
      <WorkloadPicker
        kinds={['deployments', 'statefulsets']}
        extraColumn={{
          header: t('scale.autoscaler'),
          cell: (r) => {
            const h = hpaFor(r.kind, r.namespace, r.name);
            return h ? (
              <Badge tone="info" title={t('scale.hpaHint')}>
                HPA {String(h.minReplicas)}–{String(h.maxReplicas)}
              </Badge>
            ) : null;
          },
        }}
        action={(r) =>
          can('workloads.scale') ? (
            <button
              type="button"
              className="btn sm"
              onClick={() => ops.open('scale', { key: r.key, kind: r.kind, name: r.name, namespace: r.namespace, replicas: Number(r.replicas ?? 0) })}
            >
              <Scaling size={14} /> {t('scale.action')}
            </button>
          ) : null
        }
      />
      <p className="small muted" style={{ marginTop: 10 }}>{t('scale.hpaNote')}</p>
      {ops.dialog}
    </>
  );
}
