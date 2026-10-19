import i18n from '@/i18n';

export function formatBytes(n: number | null | undefined, digits = 1): string {
  if (n === null || n === undefined || Number.isNaN(n)) return '—';
  const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB', 'PiB'];
  let v = Math.abs(n);
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i += 1;
  }
  return `${n < 0 ? '-' : ''}${v.toFixed(i === 0 ? 0 : digits)} ${units[i]}`;
}

export function formatCpu(cores: number | null | undefined): string {
  if (cores === null || cores === undefined || Number.isNaN(cores)) return '—';
  if (cores < 1) return `${Math.round(cores * 1000)}m`;
  return `${cores.toFixed(cores < 10 ? 2 : 1)}`;
}

export function formatPercent(ratio: number | null | undefined, digits = 0): string {
  if (ratio === null || ratio === undefined || !Number.isFinite(ratio)) return '—';
  return `${(ratio * 100).toFixed(digits)}%`;
}

export function ageSeconds(ts: string | number | null | undefined): number | null {
  if (ts === null || ts === undefined || ts === '') return null;
  const ms = typeof ts === 'number' ? (ts > 1e12 ? ts : ts * 1000) : Date.parse(ts);
  if (Number.isNaN(ms)) return null;
  return Math.max(0, Math.floor((Date.now() - ms) / 1000));
}

/** Compact age like kubectl: 45s, 12m, 3h, 5d. */
export function formatAge(ts: string | number | null | undefined): string {
  const s = ageSeconds(ts);
  if (s === null) return '—';
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86400) return `${Math.floor(s / 3600)}h`;
  return `${Math.floor(s / 86400)}d`;
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return '—';
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
  return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
}

export function formatDate(ts: string | number | null | undefined): string {
  if (ts === null || ts === undefined || ts === '') return '—';
  const d = typeof ts === 'number' ? new Date(ts > 1e12 ? ts : ts * 1000) : new Date(ts);
  if (Number.isNaN(d.getTime())) return String(ts);
  return d.toLocaleString(i18n.language === 'en' ? 'en-GB' : 'it-IT', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

export function plural(kindKey: string): string {
  return kindKey;
}

export function classNames(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(' ');
}
