import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { ApiError } from '@/api/client';
import { useApi } from '@/hooks/api';
import { ErrorPanel } from '@/components/ErrorPanel';
import { HelpLink } from '@/components/HelpLink';
import { Alert, Card, Empty, Loading, PageHeader } from '@/components/ui';

interface Registries {
  connected: boolean;
  error?: { code: string; message: string; details?: string | null };
  search: string[];
  configured: Record<string, unknown>;
  imagesByRegistry?: Record<string, number>;
}

export default function Registries() {
  const { t } = useTranslation('podman');
  const q = useApi<Registries>('/podman/registries');
  return (
    <>
      <PageHeader title={t('registriesTitle')} subtitle={t('registriesSubtitle')} help={<HelpLink slug="cos-e-podman" />} />
      {q.isLoading && <Loading />}
      {q.error && <ErrorPanel error={q.error} onRetry={() => void q.refetch()} />}
      {q.data && !q.data.connected && (
        <ErrorPanel
          error={new ApiError(503, { code: q.data.error?.code ?? 'podman_unavailable', message: q.data.error?.message ?? '', details: q.data.error?.details })}
          onRetry={() => void q.refetch()}
        />
      )}
      {q.data?.connected && (
        <>
          <Alert tone="info" title={t('registriesExplainTitle')}>
            <p>{t('registriesExplain')}</p>
            <p className="small">{t('registriesK8sNote')}</p>
          </Alert>
          <div className="grid cols-2">
            <Card title={t('searchRegistries')}>
              <p className="small muted">{t('searchRegistriesHelp')}</p>
              {q.data.search.length ? (
                <ol>
                  {q.data.search.map((r) => (
                    <li key={r}>
                      <code>{r}</code>
                    </li>
                  ))}
                </ol>
              ) : (
                <Empty>{t('noSearchRegistries')}</Empty>
              )}
            </Card>
            <Card title={t('imagesByRegistry')}>
              {Object.keys(q.data.imagesByRegistry ?? {}).length ? (
                <table className="data">
                  <caption className="sr-only">{t('imagesByRegistry')}</caption>
                  <thead>
                    <tr>
                      <th scope="col">{t('registry')}</th>
                      <th scope="col" className="num">{t('imageCount')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(q.data.imagesByRegistry ?? {})
                      .sort((a, b) => b[1] - a[1])
                      .map(([r, n]) => (
                        <tr key={r}>
                          <td>
                            <Link to={`/podman/images?q=${encodeURIComponent(r)}`}>
                              <code>{r}</code>
                            </Link>
                          </td>
                          <td className="num">{n}</td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              ) : (
                <Empty>{t('noImages')}</Empty>
              )}
            </Card>
          </div>
          <div className="section" style={{ marginTop: 14 }}>
            <Card title={t('configuredRegistries')}>
              <p className="small muted">{t('configuredRegistriesHelp')}</p>
              {Object.keys(q.data.configured).length ? (
                <pre className="code">{JSON.stringify(q.data.configured, null, 2)}</pre>
              ) : (
                <Empty>{t('noConfiguredRegistries')}</Empty>
              )}
            </Card>
          </div>
        </>
      )}
    </>
  );
}
