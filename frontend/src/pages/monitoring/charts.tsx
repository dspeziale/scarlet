import { useId, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useApi } from '@/hooks/api';
import { ErrorPanel } from '@/components/ErrorPanel';
import { Card, Loading, Segmented } from '@/components/ui';
import { formatDate } from '@/utils/format';

export interface Sources {
  metricsServer: boolean;
  prometheus: { configured: boolean; ok: boolean; error?: string; targets?: number; latencyMs?: number };
  queries: string[];
  ranges: string[];
}

interface Series {
  labels: Record<string, string>;
  values: [number, number][];
}

const COLORS = ['var(--primary)', 'var(--ok)', 'var(--warn)', 'var(--purple)', 'var(--err)', 'var(--info)'];

/** Minimal SVG line chart: only renders real points coming from Prometheus. */
export function LineChart({ series, format, label, height = 160 }: { series: Series[]; format: (v: number) => string; label: string; height?: number }) {
  const { t } = useTranslation('monitoring');
  const titleId = useId();
  const all = series.flatMap((s) => s.values);
  if (!all.length) return <p className="muted small">{t('noDataPoints')}</p>;
  const W = 640;
  const H = height;
  const pad = { l: 8, r: 8, t: 8, b: 8 };
  const xs = all.map((p) => p[0]);
  const ys = all.map((p) => p[1]);
  const x0 = Math.min(...xs);
  const x1 = Math.max(...xs);
  const y1 = Math.max(...ys, 0) || 1;
  const sx = (x: number) => pad.l + ((x - x0) / Math.max(1, x1 - x0)) * (W - pad.l - pad.r);
  const sy = (y: number) => H - pad.b - (y / y1) * (H - pad.t - pad.b);
  const last = series.map((s) => s.values[s.values.length - 1]?.[1]).filter((v) => v !== undefined) as number[];
  return (
    <figure style={{ margin: 0 }}>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} role="img" aria-labelledby={titleId} preserveAspectRatio="none" style={{ background: 'var(--surface-2)', borderRadius: 'var(--radius)' }}>
        <title id={titleId}>
          {label}: {t('chartSummary', { from: formatDate(x0), to: formatDate(x1), max: format(y1), last: last.map(format).join(', ') })}
        </title>
        <line x1={pad.l} x2={W - pad.r} y1={sy(y1)} y2={sy(y1)} stroke="var(--border)" strokeDasharray="4 4" />
        <line x1={pad.l} x2={W - pad.r} y1={sy(y1 / 2)} y2={sy(y1 / 2)} stroke="var(--border)" strokeDasharray="4 4" />
        {series.map((s, i) => (
          <polyline
            key={i}
            fill="none"
            stroke={COLORS[i % COLORS.length]}
            strokeWidth={2}
            vectorEffect="non-scaling-stroke"
            points={s.values.map(([x, y]) => `${sx(x).toFixed(1)},${sy(y).toFixed(1)}`).join(' ')}
          />
        ))}
      </svg>
      <figcaption className="row small muted between" style={{ marginTop: 4 }}>
        <span>{formatDate(x0)}</span>
        <span>
          {t('max')}: {format(y1)} · {t('last')}: {last.map(format).join(', ')}
        </span>
        <span>{formatDate(x1)}</span>
      </figcaption>
    </figure>
  );
}

/** Historical chart from a named Prometheus query; renders nothing invented when Prometheus is absent. */
export function PromHistory({ query, title, format, sources }: { query: string; title: string; format: (v: number) => string; sources?: Sources }) {
  const { t } = useTranslation('monitoring');
  const [range, setRange] = useState('1h');
  const enabled = !!sources?.prometheus.ok;
  const q = useApi<{ series: Series[] }>(enabled ? `/monitoring/prometheus/${query}` : null, { range }, { refetchInterval: 60_000 });
  if (!enabled) return null;
  return (
    <Card
      title={title}
      actions={
        <Segmented
          label={t('range')}
          value={range}
          onChange={setRange}
          options={(sources?.ranges ?? ['1h', '6h', '24h', '7d']).map((r) => ({ value: r, label: r }))}
        />
      }
    >
      {q.isLoading && <Loading />}
      {q.error && <ErrorPanel error={q.error} onRetry={() => void q.refetch()} />}
      {q.data && <LineChart series={q.data.series} format={format} label={title} />}
      <p className="small muted" style={{ margin: '6px 0 0' }}>{t('sourcePrometheus')}</p>
    </Card>
  );
}
