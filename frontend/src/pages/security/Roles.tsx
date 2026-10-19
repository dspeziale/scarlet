import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { ShieldCheck } from 'lucide-react';
import { useAuth } from '@/auth/AuthContext';
import { ErrorPanel } from '@/components/ErrorPanel';
import { Alert, Badge, Card, Loading, PageHeader } from '@/components/ui';
import { useRbac } from './rbac';

export default function Roles() {
  const { t } = useTranslation('security');
  const { user } = useAuth();
  const q = useRbac();
  return (
    <>
      <PageHeader title={t('roles.title')} subtitle={t('roles.subtitle')} />
      <Alert tone="info">{t('roles.enforced')}</Alert>
      {q.isLoading && <Loading />}
      {q.error && <ErrorPanel error={q.error} onRetry={() => void q.refetch()} />}
      {q.data && (
        <div className="grid cols-3">
          {q.data.roles.map((r) => (
            <Card
              key={r.id}
              title={
                <span className="row">
                  <ShieldCheck size={16} aria-hidden="true" /> {t(`common:roles.${r.id}`)}
                  {user?.role === r.id && <Badge tone="info">{t('roles.yours')}</Badge>}
                </span>
              }
            >
              <p>{t(`roles.describe.${r.id}`)}</p>
              <h3 className="small">{t('roles.can')}</h3>
              <ul className="small">
                {(t(`roles.can_${r.id}`, { returnObjects: true }) as string[]).map((x) => (
                  <li key={x}>{x}</li>
                ))}
              </ul>
              <p className="small muted">{t('roles.permCount', { count: r.permissions.length, total: q.data!.permissions.length })}</p>
            </Card>
          ))}
        </div>
      )}
      <p style={{ marginTop: 14 }}>
        <Link to="/security/permissions">{t('roles.seeMatrix')}</Link>
      </p>
    </>
  );
}
