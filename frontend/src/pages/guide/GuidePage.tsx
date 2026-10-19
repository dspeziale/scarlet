import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { marked } from 'marked';
import DOMPurify from 'dompurify';
import { Search } from 'lucide-react';
import { article, articles, CATEGORIES, searchGuide, type Article } from '@/guide';
import { Card, Empty, PageHeader } from '@/components/ui';

/** Renders bundled Markdown; guide:<slug> and app:<path> links become in-app navigation. */
function renderMarkdown(md: string): string {
  const html = marked.parse(md, { async: false, gfm: true }) as string;
  const clean = DOMPurify.sanitize(html, { USE_PROFILES: { html: true } });
  return clean
    .replace(/href="guide:([\w-]+)"/g, 'href="/guide/$1" data-internal="1"')
    .replace(/href="app:([^"]+)"/g, 'href="$1" data-internal="1"');
}

function ArticleView({ a }: { a: Article }) {
  const { t, i18n } = useTranslation('guide');
  const navigate = useNavigate();
  const ref = useRef<HTMLDivElement>(null);
  const html = useMemo(() => renderMarkdown(a.body), [a.body]);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const onClick = (e: MouseEvent) => {
      const link = (e.target as HTMLElement).closest('a');
      if (link?.dataset.internal) {
        e.preventDefault();
        navigate(link.getAttribute('href') ?? '/');
      } else if (link && /^https?:/.test(link.getAttribute('href') ?? '')) {
        link.setAttribute('target', '_blank');
        link.setAttribute('rel', 'noopener noreferrer');
      }
    };
    el.addEventListener('click', onClick);
    return () => el.removeEventListener('click', onClick);
  }, [navigate, html]);
  useEffect(() => {
    document.getElementById('main')?.scrollTo({ top: 0 });
  }, [a.slug]);
  const related = a.related.map((s) => article(i18n.language, s)).filter((x): x is Article => !!x);
  return (
    <article>
      <div className="breadcrumbs">
        <Link to="/guide">{t('title')}</Link> / {t(`category.${a.category}`)}
      </div>
      <h1>{a.title}</h1>
      {a.summary && <p className="muted" style={{ fontSize: 15 }}>{a.summary}</p>}
      <div className="prose" ref={ref} dangerouslySetInnerHTML={{ __html: html }} />
      {related.length > 0 && (
        <Card title={t('related')} className="section">
          <ul>
            {related.map((r) => (
              <li key={r.slug}>
                <Link to={`/guide/${r.slug}`}>{r.title}</Link> — <span className="small muted">{r.summary}</span>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </article>
  );
}

export default function GuidePage() {
  const { slug } = useParams();
  const { t, i18n } = useTranslation('guide');
  const [q, setQ] = useState('');
  const list = articles(i18n.language);
  const current = slug ? article(i18n.language, slug) : undefined;
  const hits = q.trim().length >= 2 ? searchGuide(i18n.language, q, 20) : [];

  return (
    <>
      <PageHeader title={t('title')} subtitle={t('subtitle')} />
      <div className="guide-layout">
        <nav className="guide-toc card" aria-label={t('toc')} style={{ padding: 12 }}>
          <div className="row" style={{ marginBottom: 8 }}>
            <Search size={15} className="muted" aria-hidden="true" />
            <input className="input sm" style={{ flex: 1 }} placeholder={t('searchPlaceholder')} aria-label={t('searchPlaceholder')} value={q} onChange={(e) => setQ(e.target.value)} />
          </div>
          {CATEGORIES.map((c) => {
            const items = list.filter((a) => a.category === c);
            if (!items.length) return null;
            return (
              <div key={c}>
                <h4>{t(`category.${c}`)}</h4>
                {items.map((a) => (
                  <Link key={a.slug} to={`/guide/${a.slug}`} className={a.slug === slug ? 'active' : undefined} aria-current={a.slug === slug ? 'page' : undefined}>
                    {a.title}
                  </Link>
                ))}
              </div>
            );
          })}
        </nav>
        <div style={{ minWidth: 0 }}>
          {q.trim().length >= 2 ? (
            <Card title={t('results', { count: hits.length })}>
              {hits.length === 0 ? (
                <Empty>{t('noResults')}</Empty>
              ) : (
                <ul style={{ listStyle: 'none', padding: 0, margin: 0 }} className="stack">
                  {hits.map((h) => (
                    <li key={h.article.slug}>
                      <Link to={`/guide/${h.article.slug}`} onClick={() => setQ('')}><strong>{h.article.title}</strong></Link>
                      <span className="badge tone-muted" style={{ marginLeft: 8 }}>{t(`category.${h.article.category}`)}</span>
                      <div className="small muted">{h.snippet}</div>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          ) : current ? (
            <ArticleView a={current} />
          ) : slug ? (
            <Empty>{t('notFound')}</Empty>
          ) : (
            <div className="stack" style={{ gap: 14 }}>
              <Card title={t('start')}>
                <p>{t('intro')}</p>
                <p><Link className="btn primary" to="/guide/introduzione">{t('readIntro')}</Link></p>
              </Card>
              <div className="grid cols-3">
                {CATEGORIES.map((c) => {
                  const items = list.filter((a) => a.category === c);
                  if (!items.length) return null;
                  return (
                    <Card key={c} title={t(`category.${c}`)}>
                      <ul className="small" style={{ paddingLeft: 18, margin: 0 }}>
                        {items.map((a) => (
                          <li key={a.slug}><Link to={`/guide/${a.slug}`}>{a.title}</Link></li>
                        ))}
                      </ul>
                    </Card>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      </div>
    </>
  );
}
