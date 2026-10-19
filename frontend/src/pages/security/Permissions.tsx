import { useTranslation } from 'react-i18next';
import { Check, Minus } from 'lucide-react';
import { ErrorPanel } from '@/components/ErrorPanel';
import { Card, Loading, PageHeader } from '@/components/ui';
import { useRbac } from './rbac';

export default function Permissions() {
  const { t } = useTranslation('security');
  const q = useRbac();
  return (
    <>
      <PageHeader title={t('perms.title')} subtitle={t('perms.subtitle')} />
      {q.isLoading && <Loading />}
      {q.error && <ErrorPanel error={q.error} onRetry={() => void q.refetch()} />}
      {q.data && (
        <Card flush>
          <div className="table-wrap">
            <table className="data">
              <caption className="sr-only">{t('perms.title')}</caption>
              <thead>
                <tr>
                  <th scope="col">{t('perms.permission')}</th>
                  <th scope="col">{t('perms.meaning')}</th>
                  {q.data.roles.map((r) => (
                    <th key={r.id} scope="col" style={{ textAlign: 'center' }}>
                      {t(`common:roles.${r.id}`)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {q.data.permissions.map((p) => (
                  <tr key={p}>
                    <th scope="row" style={{ background: 'transparent', position: 'static' }}>
                      <code>{p}</code>
                    </th>
                    <td className="small">{t(`perms.describe.${p}`, { defaultValue: p })}</td>
                    {q.data!.roles.map((r) => {
                      const has = r.permissions.includes(p);
                      return (
                        <td key={r.id} style={{ textAlign: 'center' }}>
                          {has ? <Check size={16} className="check-ok" aria-label={t('perms.granted')} /> : <Minus size={16} className="muted" aria-label={t('perms.notGranted')} />}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </>
  );
}
