import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { BookOpen } from 'lucide-react';
import { article } from '@/guide';

/** Contextual link to a guide article ("Cos'è un Deployment?", "Come risolvere ImagePullBackOff"). */
export function HelpLink({ slug, label, className }: { slug: string | null | undefined; label?: string; className?: string }) {
  const { t, i18n } = useTranslation();
  if (!slug) return null;
  const a = article(i18n.language, slug);
  if (!a) return null;
  return (
    <Link to={`/guide/${slug}`} className={`help-link ${className ?? ''}`}>
      <BookOpen size={15} aria-hidden="true" />
      {label ?? t('openGuide') + ': ' + a.title}
    </Link>
  );
}

export function KindHelp({ kind, slug }: { kind: string; slug: string | null | undefined }) {
  const { t } = useTranslation();
  return <HelpLink slug={slug} label={t('helpWhatIs', { kind })} />;
}
