import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { BookOpen, Box, Container, FileText, Search, Zap } from 'lucide-react';
import { Dialog } from '../Dialog';
import { useApi, useDebounced } from '@/hooks/api';
import { searchGuide } from '@/guide';
import { resourceLink } from '@/utils/links';

interface Hit {
  type: string;
  kind?: string;
  name: string;
  namespace?: string | null;
  id?: string;
  image?: string;
  state?: string;
  reason?: string;
  message?: string;
  eventType?: string;
  match?: string;
}

interface Entry {
  group: string;
  icon: JSX.Element;
  title: string;
  sub?: string;
  to: string;
}

export function GlobalSearch({ onClose }: { onClose: () => void }) {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const [q, setQ] = useState('');
  const [sel, setSel] = useState(0);
  const dq = useDebounced(q.trim(), 250);
  const remote = useApi<{ items: Hit[]; errors: string[] }>(dq.length >= 2 ? '/search' : null, { q: dq });

  const entries = useMemo<Entry[]>(() => {
    const out: Entry[] = [];
    for (const h of remote.data?.items ?? []) {
      if (h.type === 'k8s') {
        const to = resourceLink(h.kind, h.namespace, h.name);
        if (to) out.push({ group: t('searchGroups.k8s'), icon: <Box size={16} />, title: h.name, sub: `${h.kind}${h.namespace ? ' · ' + h.namespace : ''}`, to });
      } else if (h.type === 'event') {
        const to = resourceLink(h.kind, h.namespace, h.name);
        if (to) out.push({ group: t('searchGroups.events'), icon: <Zap size={16} />, title: `${h.reason}: ${h.name}`, sub: h.message, to: to + '?tab=events' });
      } else if (h.type === 'podman_container') {
        out.push({ group: t('searchGroups.podman'), icon: <Container size={16} />, title: h.name, sub: `${h.image} · ${h.state}`, to: `/podman/containers/${encodeURIComponent(h.id ?? h.name)}` });
      } else if (h.type === 'podman_image') {
        out.push({ group: t('searchGroups.podman'), icon: <Container size={16} />, title: h.name, sub: t('searchGroups.image'), to: `/podman/images?q=${encodeURIComponent(h.name)}` });
      }
    }
    if (dq.length >= 2) {
      for (const g of searchGuide(i18n.language, dq, 6)) {
        out.push({ group: t('searchGroups.guide'), icon: <BookOpen size={16} />, title: g.article.title, sub: g.article.summary, to: `/guide/${g.article.slug}` });
      }
      out.push({ group: t('searchGroups.logs'), icon: <FileText size={16} />, title: t('searchInLogs', { q: dq }), sub: t('searchInLogsHint'), to: `/monitoring/logs?filter=${encodeURIComponent(dq)}` });
    }
    return out;
  }, [remote.data, dq, i18n.language, t]);

  useEffect(() => setSel(0), [entries.length]);
  const go = (e: Entry) => {
    navigate(e.to);
    onClose();
  };

  let lastGroup = '';
  return (
    <Dialog title={t('searchTitle')} onClose={onClose} className="search-dialog">
      <div className="row" style={{ marginBottom: 10 }}>
        <Search size={18} className="muted" aria-hidden="true" />
        <input
          className="input"
          style={{ flex: 1 }}
          value={q}
          data-autofocus
          placeholder={t('searchPlaceholder')}
          aria-label={t('searchPlaceholder')}
          aria-controls="search-results"
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'ArrowDown') {
              e.preventDefault();
              setSel((s) => Math.min(entries.length - 1, s + 1));
            } else if (e.key === 'ArrowUp') {
              e.preventDefault();
              setSel((s) => Math.max(0, s - 1));
            } else if (e.key === 'Enter' && entries[sel]) {
              go(entries[sel]);
            }
          }}
        />
      </div>
      {dq.length < 2 && <p className="muted small">{t('searchHelp')}</p>}
      {remote.isFetching && <p className="muted small">{t('searching')}</p>}
      {dq.length >= 2 && !remote.isFetching && entries.length <= 1 && <p className="muted">{t('noMatches')}</p>}
      <ul className="search-results" id="search-results" role="listbox" aria-label={t('searchTitle')}>
        {entries.map((e, i) => {
          const header = e.group !== lastGroup ? <li className="search-group" role="presentation">{e.group}</li> : null;
          lastGroup = e.group;
          return (
            <FragmentWithHeader key={`${e.to}-${i}`} header={header}>
              <li role="option" aria-selected={i === sel}>
                <button type="button" onClick={() => go(e)} onMouseEnter={() => setSel(i)}>
                  {e.icon}
                  <span style={{ minWidth: 0 }}>
                    <div className="ellipsis">{e.title}</div>
                    {e.sub && <div className="small muted ellipsis">{e.sub}</div>}
                  </span>
                </button>
              </li>
            </FragmentWithHeader>
          );
        })}
      </ul>
    </Dialog>
  );
}

function FragmentWithHeader({ header, children }: { header: JSX.Element | null; children: JSX.Element }) {
  return (
    <>
      {header}
      {children}
    </>
  );
}
