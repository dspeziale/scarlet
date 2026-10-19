import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Download, Pause, Play, Radio, RefreshCw, Square } from 'lucide-react';
import { ApiError, buildUrl, downloadUrl, get } from '@/api/client';
import { ErrorPanel } from './ErrorPanel';
import { Alert } from './ui';

const MAX_LINES = 20000; // memory cap in the browser; older lines are dropped

interface Source {
  /** e.g. /k8s/pods/ns/name/logs or /podman/containers/id/logs */
  path: string;
  /** SSE path for live streaming (Kubernetes only). */
  streamPath?: string;
  containers?: string[];
  previousSupported?: boolean;
}

function splitTs(line: string): [string, string] {
  const m = line.match(/^(\d{4}-\d{2}-\d{2}T[\d:.]+(?:Z|[+-]\d{2}:?\d{2}))\s(.*)$/);
  return m ? [m[1], m[2]] : ['', line];
}

function lineClass(text: string): string {
  if (/\b(error|fatal|panic|exception|err)\b/i.test(text)) return 'err';
  if (/\b(warn|warning)\b/i.test(text)) return 'warn';
  return '';
}

/**
 * Professional log viewer: tail with limit, previous container logs, live streaming
 * (server-limited in time and lines), pause/resume, search/filter, timestamps toggle, download.
 */
export function LogViewer({
  source,
  initialFilter = '',
  initialContainer,
  initialPrevious = false,
}: {
  source: Source;
  initialFilter?: string;
  initialContainer?: string | null;
  initialPrevious?: boolean;
}) {
  const { t } = useTranslation('logs');
  const pickContainer = () => (initialContainer && source.containers?.includes(initialContainer) ? initialContainer : source.containers?.[0] ?? '');
  const [container, setContainer] = useState(pickContainer);
  const [tail, setTail] = useState(500);
  const [previous, setPrevious] = useState(initialPrevious);
  const [showTs, setShowTs] = useState(true);
  const [filter, setFilter] = useState(initialFilter);
  const [onlyMatches, setOnlyMatches] = useState(!!initialFilter);
  const [lines, setLines] = useState<string[]>([]);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(false);
  const [live, setLive] = useState(false);
  const [paused, setPaused] = useState(false);
  const [streamInfo, setStreamInfo] = useState<string | null>(null);
  const buffer = useRef<string[]>([]);
  const pausedRef = useRef(false);
  const esRef = useRef<EventSource | null>(null);
  const box = useRef<HTMLDivElement>(null);
  const stick = useRef(true);
  pausedRef.current = paused;

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => setContainer(pickContainer()), [source.containers?.join(',')]);

  const stop = useCallback(() => {
    esRef.current?.close();
    esRef.current = null;
    setLive(false);
    setPaused(false);
  }, []);

  const load = useCallback(async () => {
    stop();
    setLoading(true);
    setError(null);
    try {
      const res = await get<{ lines: string[] }>(source.path, {
        container: container || undefined,
        tail,
        timestamps: true,
        previous: previous || undefined,
      });
      setLines(res.lines.slice(-MAX_LINES));
    } catch (e) {
      setError(e);
      setLines([]);
    } finally {
      setLoading(false);
    }
  }, [source.path, container, tail, previous, stop]);

  useEffect(() => {
    void load();
    return () => esRef.current?.close();
  }, [load]);

  const start = () => {
    if (!source.streamPath) return;
    stop();
    setError(null);
    setStreamInfo(null);
    setLines([]);
    const es = new EventSource(buildUrl(source.streamPath, { container: container || undefined, tail: Math.min(tail, 1000) }), { withCredentials: true });
    esRef.current = es;
    setLive(true);
    es.onmessage = (ev) => {
      const batch = JSON.parse(ev.data) as string[];
      if (pausedRef.current) {
        buffer.current.push(...batch);
        if (buffer.current.length > MAX_LINES) buffer.current = buffer.current.slice(-MAX_LINES);
        return;
      }
      setLines((ls) => {
        const next = ls.concat(batch);
        return next.length > MAX_LINES ? next.slice(-MAX_LINES) : next;
      });
    };
    const end = (reason: string) => {
      setStreamInfo(reason);
      es.close();
      esRef.current = null;
      setLive(false);
    };
    es.addEventListener('end', () => end(t('streamEnded')));
    es.addEventListener('limit', (ev) => {
      const d = JSON.parse((ev as MessageEvent).data) as { reason: string };
      end(d.reason === 'duration' ? t('limitDuration') : t('limitLines'));
    });
    es.addEventListener('error', (ev) => {
      const data = (ev as MessageEvent).data;
      if (data) {
        const d = JSON.parse(data) as { code: string; message: string };
        setError(new ApiError(502, { code: d.code, message: d.message }));
      } else if (es.readyState === EventSource.CLOSED || es.readyState === EventSource.CONNECTING) {
        // Connection lost: do not auto-reconnect in a loop, let the user restart.
        end(t('streamLost'));
      }
    });
  };

  const resume = () => {
    setPaused(false);
    const buffered = buffer.current;
    buffer.current = [];
    if (buffered.length) setLines((ls) => ls.concat(buffered).slice(-MAX_LINES));
  };

  useEffect(() => {
    const el = box.current;
    if (el && stick.current) el.scrollTop = el.scrollHeight;
  }, [lines]);

  const needle = filter.trim().toLowerCase();
  const view = useMemo(() => (onlyMatches && needle ? lines.filter((l) => l.toLowerCase().includes(needle)) : lines), [lines, onlyMatches, needle]);
  const matches = useMemo(() => (needle ? lines.filter((l) => l.toLowerCase().includes(needle)).length : 0), [lines, needle]);

  const highlight = (text: string) => {
    if (!needle) return text;
    const parts: (string | JSX.Element)[] = [];
    const low = text.toLowerCase();
    let i = 0;
    let k = 0;
    while (i < text.length) {
      const j = low.indexOf(needle, i);
      if (j < 0) {
        parts.push(text.slice(i));
        break;
      }
      parts.push(text.slice(i, j), <mark key={k++}>{text.slice(j, j + needle.length)}</mark>);
      i = j + needle.length;
    }
    return parts;
  };

  return (
    <div className="stack">
      <div className="row">
        {source.containers && source.containers.length > 1 && (
          <select className="input sm" value={container} onChange={(e) => setContainer(e.target.value)} aria-label={t('container')}>
            {source.containers.map((c) => (
              <option key={c}>{c}</option>
            ))}
          </select>
        )}
        <label className="row small">
          {t('tail')}
          <select className="input sm" value={tail} onChange={(e) => setTail(Number(e.target.value))}>
            {[100, 500, 1000, 2000, 5000].map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </label>
        {source.previousSupported && (
          <label className="checkbox small">
            <input type="checkbox" checked={previous} onChange={(e) => setPrevious(e.target.checked)} disabled={live} />
            {t('previous')}
          </label>
        )}
        <label className="checkbox small">
          <input type="checkbox" checked={showTs} onChange={(e) => setShowTs(e.target.checked)} />
          {t('timestamps')}
        </label>
        <button type="button" className="btn sm" onClick={() => void load()} disabled={loading}>
          <RefreshCw size={14} /> {t('reload')}
        </button>
        {source.streamPath &&
          (live ? (
            <>
              {paused ? (
                <button type="button" className="btn sm" onClick={resume}>
                  <Play size={14} /> {t('resume')}
                </button>
              ) : (
                <button type="button" className="btn sm" onClick={() => setPaused(true)}>
                  <Pause size={14} /> {t('pause')}
                </button>
              )}
              <button type="button" className="btn sm" onClick={stop}>
                <Square size={14} /> {t('stop')}
              </button>
            </>
          ) : (
            <button type="button" className="btn sm primary" onClick={start} disabled={previous}>
              <Radio size={14} /> {t('live')}
            </button>
          ))}
        <button
          type="button"
          className="btn sm"
          onClick={() => downloadUrl(source.path, { container: container || undefined, tail: 50000, timestamps: true, previous: previous || undefined, download: true })}
        >
          <Download size={14} /> {t('download')}
        </button>
      </div>
      <div className="row">
        <input
          className="input sm"
          style={{ flex: 1, maxWidth: 420 }}
          placeholder={t('filterPlaceholder')}
          aria-label={t('filterPlaceholder')}
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        />
        <label className="checkbox small">
          <input type="checkbox" checked={onlyMatches} onChange={(e) => setOnlyMatches(e.target.checked)} />
          {t('onlyMatches')}
        </label>
        <span className="small muted" aria-live="polite">
          {needle ? t('matches', { count: matches }) : ''} · {t('linesShown', { count: view.length })}
          {live && (paused ? ` · ${t('pausedBuffered', { count: buffer.current.length })}` : ` · ${t('streaming')}`)}
        </span>
      </div>
      {streamInfo && <Alert tone="info">{streamInfo}</Alert>}
      {error ? <ErrorPanel error={error} onRetry={() => void load()} /> : null}
      <div
        className="log-view"
        ref={box}
        role="log"
        aria-label={t('logArea')}
        aria-live="off"
        tabIndex={0}
        onScroll={(e) => {
          const el = e.currentTarget;
          stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
        }}
      >
        {loading && <div className="log-line">{t('loading')}</div>}
        {!loading && view.length === 0 && !error && <div className="log-line">{t('empty')}</div>}
        {view.map((l, i) => {
          const [ts, text] = splitTs(l);
          return (
            <div key={i} className={`log-line ${lineClass(text)}`}>
              {showTs && ts && <span className="ts">{ts.replace('T', ' ').replace(/\.\d+Z$/, 'Z')}</span>}
              {highlight(text)}
            </div>
          );
        })}
      </div>
    </div>
  );
}
