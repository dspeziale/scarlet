import { useMemo, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { ArrowDown, ArrowUp, Search } from 'lucide-react';
import { Empty } from './ui';

export interface Column<T> {
  id: string;
  header: ReactNode;
  cell: (row: T) => ReactNode;
  /** Value used for sorting and text filtering. */
  value?: (row: T) => string | number | null | undefined;
  numeric?: boolean;
  className?: string;
}

/** Client-side table with text filter, sorting and pagination (data comes paginated/limited from the API). */
export function DataTable<T>({
  rows,
  columns,
  rowKey,
  onRowClick,
  filterPlaceholder,
  toolbar,
  pageSize = 50,
  initialSort,
  emptyText,
  caption,
  initialFilter = '',
}: {
  rows: T[];
  columns: Column<T>[];
  rowKey: (row: T) => string;
  onRowClick?: (row: T) => void;
  filterPlaceholder?: string;
  toolbar?: ReactNode;
  pageSize?: number;
  initialSort?: { id: string; dir: 'asc' | 'desc' };
  emptyText?: ReactNode;
  caption?: string;
  /** Initial value of the text filter (e.g. from a ?q= query parameter). */
  initialFilter?: string;
}) {
  const { t } = useTranslation();
  const [q, setQ] = useState(initialFilter);
  const [sort, setSort] = useState(initialSort ?? null);
  const [page, setPage] = useState(0);

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    let out = rows;
    if (needle) {
      out = rows.filter((r) =>
        columns.some((c) => {
          const v = c.value?.(r);
          return v !== null && v !== undefined && String(v).toLowerCase().includes(needle);
        }),
      );
    }
    if (sort) {
      const col = columns.find((c) => c.id === sort.id);
      if (col?.value) {
        out = [...out].sort((a, b) => {
          const va = col.value!(a);
          const vb = col.value!(b);
          if (va === vb) return 0;
          if (va === null || va === undefined) return 1;
          if (vb === null || vb === undefined) return -1;
          const cmp = typeof va === 'number' && typeof vb === 'number' ? va - vb : String(va).localeCompare(String(vb), undefined, { numeric: true });
          return sort.dir === 'asc' ? cmp : -cmp;
        });
      }
    }
    return out;
  }, [rows, columns, q, sort]);

  const pages = Math.max(1, Math.ceil(filtered.length / pageSize));
  const current = Math.min(page, pages - 1);
  const visible = filtered.slice(current * pageSize, current * pageSize + pageSize);

  return (
    <div>
      <div className="table-toolbar">
        <div className="row" style={{ flex: 1, minWidth: 200 }}>
          <Search size={16} className="muted" aria-hidden="true" />
          <input
            className="input sm"
            style={{ flex: 1, maxWidth: 360 }}
            placeholder={filterPlaceholder ?? t('filter')}
            aria-label={filterPlaceholder ?? t('filter')}
            value={q}
            onChange={(e) => {
              setQ(e.target.value);
              setPage(0);
            }}
          />
        </div>
        {toolbar}
      </div>
      <div className="table-wrap">
        <table className="data">
          {caption && <caption className="sr-only">{caption}</caption>}
          <thead>
            <tr>
              {columns.map((c) => (
                <th
                  key={c.id}
                  className={c.numeric ? 'num' : undefined}
                  aria-sort={sort?.id === c.id ? (sort.dir === 'asc' ? 'ascending' : 'descending') : undefined}
                  scope="col"
                >
                  {c.value ? (
                    <button
                      type="button"
                      onClick={() => setSort((s) => (s?.id === c.id ? { id: c.id, dir: s.dir === 'asc' ? 'desc' : 'asc' } : { id: c.id, dir: 'asc' }))}
                    >
                      {c.header}
                      {sort?.id === c.id && (sort.dir === 'asc' ? <ArrowUp size={12} /> : <ArrowDown size={12} />)}
                    </button>
                  ) : (
                    c.header
                  )}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {visible.map((r) => (
              <tr
                key={rowKey(r)}
                className={onRowClick ? 'clickable' : undefined}
                onClick={onRowClick ? (e) => {
                  if ((e.target as HTMLElement).closest('a,button,input,select')) return;
                  onRowClick(r);
                } : undefined}
                onKeyDown={onRowClick ? (e) => e.key === 'Enter' && e.target === e.currentTarget && onRowClick(r) : undefined}
                tabIndex={onRowClick ? 0 : undefined}
              >
                {columns.map((c) => (
                  <td key={c.id} className={[c.numeric ? 'num' : '', c.className ?? ''].join(' ').trim() || undefined}>
                    {c.cell(r)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        {visible.length === 0 && <Empty>{q ? t('noMatches') : emptyText ?? t('noItems')}</Empty>}
      </div>
      <div className="table-footer">
        <span>{t('rowsCount', { count: filtered.length, total: rows.length })}</span>
        {pages > 1 && (
          <span className="row">
            <button type="button" className="btn sm" disabled={current === 0} onClick={() => setPage(current - 1)}>
              {t('prev')}
            </button>
            <span>
              {current + 1} / {pages}
            </span>
            <button type="button" className="btn sm" disabled={current >= pages - 1} onClick={() => setPage(current + 1)}>
              {t('next')}
            </button>
          </span>
        )}
      </div>
    </div>
  );
}
