import { useEffect, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import type { ContainerRow, ResourceList } from '@/api/types';
import { useAuth } from '@/auth/AuthContext';
import { useApi } from '@/hooks/api';
import { ErrorPanel } from '@/components/ErrorPanel';
import { HelpLink } from '@/components/HelpLink';
import { LogViewer } from '@/components/LogViewer';
import { NamespaceSelect } from '@/components/NamespaceSelect';
import { Alert, Card, Field, HealthBadge, Loading, PageHeader } from '@/components/ui';
import { resourceLink } from '@/utils/links';

export default function Logs() {
  const { t } = useTranslation('monitoring');
  const { can } = useAuth();
  const [params, setParams] = useSearchParams();
  const [ns, setNs] = useState(params.get('namespace') ?? '');
  const [pod, setPod] = useState(params.get('pod') ?? '');
  const filter = params.get('filter') ?? '';
  const pods = useApi<ResourceList>(ns ? '/k8s/pods' : null, { namespace: ns });
  const items = pods.data?.items ?? [];
  const selected = items.find((p) => p.name === pod);
  const containers = useMemo(() => ((selected?.containers as ContainerRow[] | undefined) ?? []).map((c) => c.name), [selected]);

  useEffect(() => {
    const next = new URLSearchParams(params);
    if (ns) next.set('namespace', ns);
    else next.delete('namespace');
    if (pod) next.set('pod', pod);
    else next.delete('pod');
    if (next.toString() !== params.toString()) setParams(next, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ns, pod]);

  if (!can('logs.read')) {
    return (
      <>
        <PageHeader title={t('logs.title')} />
        <Alert tone="warn">{t('logs.noPermission')}</Alert>
      </>
    );
  }

  return (
    <>
      <PageHeader title={t('logs.title')} subtitle={t('logs.subtitle')} help={<HelpLink slug="proc-visualizzare-log" />} />
      <Card title={t('logs.select')}>
        <div className="form-grid">
          <Field label={t('common:namespace')} htmlFor="logs-ns">
            <NamespaceSelect
              id="logs-ns"
              value={ns}
              allowAll={false}
              onChange={(v) => {
                setNs(v);
                setPod('');
              }}
            />
          </Field>
          <Field label="Pod" htmlFor="logs-pod" hint={ns ? undefined : t('logs.chooseNsFirst')}>
            <select id="logs-pod" className="input" value={pod} onChange={(e) => setPod(e.target.value)} disabled={!ns || pods.isLoading}>
              <option value="">—</option>
              {items.map((p) => (
                <option key={p.name} value={p.name}>
                  {p.name} ({String(p.status ?? p.health)})
                </option>
              ))}
            </select>
          </Field>
        </div>
        {pods.isLoading && <Loading />}
        {pods.error && <ErrorPanel error={pods.error} onRetry={() => void pods.refetch()} />}
        {ns && pods.data && items.length === 0 && <p className="muted">{t('logs.noPods')}</p>}
        {selected && (
          <p className="small row">
            <HealthBadge health={selected.health} label={String(selected.status ?? '')} />
            <Link to={resourceLink('Pod', ns, selected.name)!}>{t('logs.openPod')}</Link>
          </p>
        )}
      </Card>
      {filter && !pod && <Alert tone="info">{t('logs.filterPending', { filter })}</Alert>}
      {selected && (
        <div className="section" style={{ marginTop: 14 }}>
          <Card title={t('logs.viewer', { pod: selected.name })}>
            <LogViewer
              key={`${ns}/${pod}`}
              initialFilter={filter}
              source={{
                path: `/k8s/pods/${encodeURIComponent(ns)}/${encodeURIComponent(pod)}/logs`,
                streamPath: `/k8s/pods/${encodeURIComponent(ns)}/${encodeURIComponent(pod)}/logs/stream`,
                containers,
                previousSupported: true,
              }}
            />
          </Card>
        </div>
      )}
    </>
  );
}
