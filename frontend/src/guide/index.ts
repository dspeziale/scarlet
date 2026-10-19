// Online guide: Markdown articles bundled with the application (so the guide is always
// aligned with the installed version), in Italian and English.

export interface Article {
  slug: string;
  lang: string;
  title: string;
  summary: string;
  category: string;
  order: number;
  keywords: string[];
  related: string[];
  body: string;
}

export const CATEGORIES = [
  'intro',
  'concepts',
  'workloads',
  'networking',
  'storage',
  'config',
  'reliability',
  'troubleshooting',
  'procedures',
  'faq',
] as const;

const raw = import.meta.glob('./content/*/*.md', { query: '?raw', import: 'default', eager: true }) as Record<string, string>;

function parse(path: string, text: string): Article | null {
  const m = path.match(/\.\/content\/(\w+)\/([\w-]+)\.md$/);
  if (!m) return null;
  const [, lang, slug] = m;
  const fm = text.replace(/\r\n/g, '\n').match(/^---\n([\s\S]*?)\n---\n?([\s\S]*)$/);
  const meta: Record<string, string> = {};
  let body = text;
  if (fm) {
    for (const line of fm[1].split('\n')) {
      const i = line.indexOf(':');
      if (i > 0) meta[line.slice(0, i).trim()] = line.slice(i + 1).trim();
    }
    body = fm[2];
  }
  const list = (v?: string) => (v ? v.split(',').map((s) => s.trim()).filter(Boolean) : []);
  return {
    slug,
    lang,
    title: meta.title ?? slug,
    summary: meta.summary ?? '',
    category: meta.category ?? 'concepts',
    order: Number(meta.order ?? 100),
    keywords: list(meta.keywords),
    related: list(meta.related),
    body,
  };
}

const ARTICLES: Article[] = Object.entries(raw)
  .map(([p, t]) => parse(p, t))
  .filter((a): a is Article => a !== null);

export function articles(lang: string): Article[] {
  const own = ARTICLES.filter((a) => a.lang === lang);
  const list = own.length ? own : ARTICLES.filter((a) => a.lang === 'it');
  return [...list].sort((a, b) => CATEGORIES.indexOf(a.category as never) - CATEGORIES.indexOf(b.category as never) || a.order - b.order);
}

export function article(lang: string, slug: string): Article | undefined {
  return ARTICLES.find((a) => a.lang === lang && a.slug === slug) ?? ARTICLES.find((a) => a.lang === 'it' && a.slug === slug);
}

function normalize(s: string): string {
  return s.toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '');
}

export interface GuideHit {
  article: Article;
  score: number;
  snippet: string;
}

/** Simple ranked full-text search over title, keywords, summary and body. */
export function searchGuide(lang: string, query: string, limit = 10): GuideHit[] {
  const terms = normalize(query).split(/\s+/).filter((t) => t.length > 1);
  if (!terms.length) return [];
  const hits: GuideHit[] = [];
  for (const a of articles(lang)) {
    const title = normalize(a.title);
    const kw = normalize(a.keywords.join(' ') + ' ' + a.slug);
    const summary = normalize(a.summary);
    const body = normalize(a.body);
    let score = 0;
    let all = true;
    for (const t of terms) {
      let s = 0;
      if (title.includes(t)) s += 10;
      if (kw.includes(t)) s += 6;
      if (summary.includes(t)) s += 3;
      const n = body.split(t).length - 1;
      s += Math.min(n, 5);
      if (s === 0) all = false;
      score += s;
    }
    if (score > 0 && all) {
      const idx = body.indexOf(terms[0]);
      const plain = a.body.replace(/[#*`>|]/g, '');
      const pidx = Math.max(0, normalize(plain).indexOf(terms[0]));
      const snippet = idx >= 0 ? '…' + plain.slice(Math.max(0, pidx - 60), pidx + 120).replace(/\s+/g, ' ') + '…' : a.summary;
      hits.push({ article: a, score, snippet });
    }
  }
  return hits.sort((x, y) => y.score - x.score).slice(0, limit);
}

/** Guide article for a Kubernetes kind (contextual help). */
export const KIND_GUIDE: Record<string, string> = {
  Pod: 'pod',
  Deployment: 'deployment',
  ReplicaSet: 'replicaset',
  StatefulSet: 'statefulset',
  DaemonSet: 'daemonset',
  Job: 'job',
  CronJob: 'cronjob',
  Service: 'service',
  Ingress: 'ingress',
  Endpoints: 'networking',
  PersistentVolume: 'persistent-volume',
  PersistentVolumeClaim: 'persistent-volume-claim',
  StorageClass: 'storage-class',
  ConfigMap: 'configmap',
  Secret: 'secret',
  Node: 'node',
  Namespace: 'namespace',
  Event: 'troubleshooting',
  PodDisruptionBudget: 'alta-disponibilita',
  HorizontalPodAutoscaler: 'replica',
};

/** Guide article for a diagnosed problem. */
export const REASON_GUIDE: Record<string, string> = {
  CrashLoopBackOff: 'crashloopbackoff',
  HighRestarts: 'crashloopbackoff',
  ImagePullBackOff: 'imagepullbackoff',
  ErrImagePull: 'imagepullbackoff',
  OOMKilled: 'oomkilled',
  Pending: 'pending',
  NodeNotReady: 'node-notready',
  PodFailed: 'pod-failed-unknown',
  PodUnknown: 'pod-failed-unknown',
  CreateContainerConfigError: 'createcontainerconfigerror',
  PVCPending: 'persistent-volume-claim',
};
