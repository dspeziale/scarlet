import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Empty, PageHeader } from '@/components/ui';

export default function NotFound() {
  const { t } = useTranslation();
  return (
    <>
      <PageHeader title={t('pageNotFound')} />
      <Empty>
        <p>{t('pageNotFoundText')}</p>
        <Link className="btn primary" to="/">
          {t('goHome')}
        </Link>
      </Empty>
    </>
  );
}
