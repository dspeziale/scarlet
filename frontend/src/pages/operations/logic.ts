// Pure logic shared by the image onboarding and deploy wizards (mirrors backend validation in pkm/k8s/manifests.py).

export type ProbeType = 'none' | 'http' | 'tcp';

export interface ProbeSpec {
  type: ProbeType;
  path: string;
  port: number | null;
  initial_delay: number;
  period: number;
  failure_threshold: number;
}

export interface DeploySpec {
  name: string;
  namespace: string;
  create_namespace: boolean;
  image: string;
  tag: string;
  image_pull_secret: string | null;
  replicas: number;
  port: number | null;
  protocol: 'TCP' | 'UDP';
  cpu_request: string | null;
  cpu_limit: string | null;
  memory_request: string | null;
  memory_limit: string | null;
  env: { name: string; value: string }[];
  storage: {
    enabled: boolean;
    size: string;
    storage_class: string | null;
    mount_path: string;
    access_mode: 'ReadWriteOnce' | 'ReadWriteMany' | 'ReadOnlyMany' | 'ReadWriteOncePod';
  };
  networking: {
    service_type: 'none' | 'ClusterIP' | 'NodePort' | 'LoadBalancer';
    service_port: number | null;
    node_port: number | null;
    ingress: { enabled: boolean; host: string; path: string; class_name: string | null; tls_secret: string | null };
  };
  readiness: ProbeSpec;
  liveness: ProbeSpec;
}

export const emptyProbe = (): ProbeSpec => ({ type: 'none', path: '/', port: null, initial_delay: 5, period: 10, failure_threshold: 3 });

export function defaultSpec(): DeploySpec {
  return {
    name: '',
    namespace: 'default',
    create_namespace: false,
    image: '',
    tag: '',
    image_pull_secret: null,
    replicas: 2,
    port: null,
    protocol: 'TCP',
    cpu_request: '100m',
    cpu_limit: null,
    memory_request: '128Mi',
    memory_limit: '256Mi',
    env: [],
    storage: { enabled: false, size: '1Gi', storage_class: null, mount_path: '/data', access_mode: 'ReadWriteOnce' },
    networking: { service_type: 'ClusterIP', service_port: null, node_port: null, ingress: { enabled: false, host: '', path: '/', class_name: null, tls_secret: null } },
    readiness: emptyProbe(),
    liveness: emptyProbe(),
  };
}

const DNS_LABEL = /^[a-z0-9]([-a-z0-9]*[a-z0-9])?$/;
const DNS_SUBDOMAIN = /^[a-z0-9]([-a-z0-9]*[a-z0-9])?(\.[a-z0-9]([-a-z0-9]*[a-z0-9])?)*$/;
const IMAGE_REPO = /^[a-z0-9]+([._/:-][a-z0-9]+)*$/;
const TAG = /^[\w][\w.-]{0,127}$/;
const CPU = /^([0-9]+m|[0-9]+(\.[0-9]{1,3})?)$/;
const MEM = /^[0-9]+(Ki|Mi|Gi|Ti|k|M|G|T)?$/;
const PATH = /^\/[A-Za-z0-9._~!$&'()*+,;=:@%/-]*$/;
const ENV_NAME = /^[A-Za-z_][A-Za-z0-9_.-]*$/;

export const isDnsLabel = (v: string, max = 63) => v.length <= max && DNS_LABEL.test(v);
export const isDnsSubdomain = (v: string) => v.length <= 253 && DNS_SUBDOMAIN.test(v);

export function cpuCores(v: string | null | undefined): number | null {
  if (!v || !CPU.test(v)) return null;
  return v.endsWith('m') ? Number(v.slice(0, -1)) / 1000 : Number(v);
}

const MEM_MULT: Record<string, number> = { '': 1, k: 1e3, M: 1e6, G: 1e9, T: 1e12, Ki: 2 ** 10, Mi: 2 ** 20, Gi: 2 ** 30, Ti: 2 ** 40 };
export function memBytes(v: string | null | undefined): number | null {
  if (!v || !MEM.test(v)) return null;
  const m = v.match(/^([0-9]+)(\w*)$/)!;
  return Number(m[1]) * (MEM_MULT[m[2]] ?? 1);
}

/** Turns any string (e.g. a repository basename) into a DNS-1123 label usable as application name. */
export function sanitizeName(input: string, max = 50): string {
  let s = input
    .toLowerCase()
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .replace(/[^a-z0-9-]+/g, '-')
    .replace(/-+/g, '-')
    .replace(/^-+/, '');
  s = s.slice(0, max).replace(/-+$/, '');
  return s || 'app';
}

export interface ImageRef {
  registry: string;
  repository: string;
  tag: string | null;
  digest: string | null;
}

/** Splits "registry:5000/team/app:1.2" into repository (with registry) and tag. */
export function splitImage(ref: string): { image: string; tag: string } {
  const s = ref.trim();
  const at = s.indexOf('@');
  if (at >= 0) return { image: s.slice(0, at), tag: s.slice(at + 1) };
  const slash = s.lastIndexOf('/');
  const colon = s.lastIndexOf(':');
  if (colon > slash) return { image: s.slice(0, colon), tag: s.slice(colon + 1) };
  return { image: s, tag: '' };
}

export function repoBasename(image: string): string {
  const { image: repo } = splitImage(image);
  const parts = repo.split('/');
  return parts[parts.length - 1] || repo;
}

export type Errors = Partial<Record<string, string>>;

/** Validates a spec; returns error codes keyed by field path (codes are i18n keys under deploy:err.*). */
export function validateSpec(s: DeploySpec): Errors {
  const e: Errors = {};
  if (!s.name) e.name = 'required';
  else if (!isDnsLabel(s.name, 50)) e.name = 'dnsLabel';
  if (!s.namespace) e.namespace = 'required';
  else if (!isDnsLabel(s.namespace)) e.namespace = 'dnsLabel';
  const img = s.image.trim();
  if (!img) e.image = 'required';
  else if (img.includes('@') || (img.split('/').pop() ?? '').includes(':')) e.image = 'tagInImage';
  else if (!IMAGE_REPO.test(img) || img.length > 255) e.image = 'imageFormat';
  if (!s.tag.trim()) e.tag = 'required';
  else if (!TAG.test(s.tag.trim())) e.tag = 'tagFormat';
  if (s.image_pull_secret && !isDnsSubdomain(s.image_pull_secret)) e.image_pull_secret = 'dnsSubdomain';
  if (!Number.isInteger(s.replicas) || s.replicas < 0 || s.replicas > 50) e.replicas = 'replicasRange';
  if (s.port !== null && (!Number.isInteger(s.port) || s.port < 1 || s.port > 65535)) e.port = 'portRange';
  for (const f of ['cpu_request', 'cpu_limit'] as const) if (s[f] && cpuCores(s[f]) === null) e[f] = 'cpuFormat';
  for (const f of ['memory_request', 'memory_limit'] as const) if (s[f] && memBytes(s[f]) === null) e[f] = 'memFormat';
  if (!e.cpu_request && !e.cpu_limit && s.cpu_request && s.cpu_limit && cpuCores(s.cpu_request)! > cpuCores(s.cpu_limit)!) e.cpu_limit = 'requestOverLimit';
  if (!e.memory_request && !e.memory_limit && s.memory_request && s.memory_limit && memBytes(s.memory_request)! > memBytes(s.memory_limit)!)
    e.memory_limit = 'requestOverLimit';
  s.env.forEach((v, i) => {
    if (!ENV_NAME.test(v.name) || v.name.length > 128) e[`env.${i}`] = 'envName';
  });
  if (new Set(s.env.map((v) => v.name)).size !== s.env.length) e.env = 'envDuplicate';
  if (s.storage.enabled) {
    if (!memBytes(s.storage.size)) e['storage.size'] = 'memFormat';
    if (!PATH.test(s.storage.mount_path) || s.storage.mount_path === '/') e['storage.mount_path'] = 'mountPath';
    if (s.storage.storage_class && !isDnsSubdomain(s.storage.storage_class)) e['storage.storage_class'] = 'dnsSubdomain';
  }
  const n = s.networking;
  if (n.service_type !== 'none' && !s.port) e['networking.service_type'] = 'serviceNeedsPort';
  if (n.service_port !== null && (n.service_port < 1 || n.service_port > 65535)) e['networking.service_port'] = 'portRange';
  if (n.node_port !== null) {
    if (n.node_port < 30000 || n.node_port > 32767) e['networking.node_port'] = 'nodePortRange';
    else if (n.service_type !== 'NodePort' && n.service_type !== 'LoadBalancer') e['networking.node_port'] = 'nodePortType';
  }
  if (n.ingress.enabled) {
    if (n.service_type === 'none') e['networking.ingress.enabled'] = 'ingressNeedsService';
    if (!n.ingress.host) e['networking.ingress.host'] = 'required';
    else if (!isDnsSubdomain(n.ingress.host.toLowerCase().replace(/^\*\./, 'x.'))) e['networking.ingress.host'] = 'hostFormat';
    if (!PATH.test(n.ingress.path)) e['networking.ingress.path'] = 'pathFormat';
    if (n.ingress.tls_secret && !isDnsSubdomain(n.ingress.tls_secret)) e['networking.ingress.tls_secret'] = 'dnsSubdomain';
    if (n.ingress.class_name && !isDnsSubdomain(n.ingress.class_name)) e['networking.ingress.class_name'] = 'dnsSubdomain';
  }
  for (const p of ['readiness', 'liveness'] as const) {
    const pr = s[p];
    if (pr.type === 'none') continue;
    if (!(pr.port || s.port)) e[`${p}.port`] = 'probeNeedsPort';
    if (pr.port !== null && (pr.port < 1 || pr.port > 65535)) e[`${p}.port`] = 'portRange';
    if (pr.type === 'http' && !PATH.test(pr.path)) e[`${p}.path`] = 'pathFormat';
  }
  return e;
}

/** Wizard steps and the fields they own (used to block "Next" on invalid fields). */
export const DEPLOY_STEPS = ['name', 'image', 'tag', 'replicas', 'port', 'cpu', 'memory', 'storage', 'networking', 'health', 'summary', 'deploy'] as const;
export type DeployStep = (typeof DEPLOY_STEPS)[number];

export function stepOf(field: string): DeployStep {
  if (field === 'name' || field === 'namespace') return 'name';
  if (field === 'image' || field === 'image_pull_secret') return 'image';
  if (field === 'tag') return 'tag';
  if (field === 'replicas') return 'replicas';
  if (field === 'port' || field === 'protocol' || field.startsWith('env')) return 'port';
  if (field.startsWith('cpu')) return 'cpu';
  if (field.startsWith('memory')) return 'memory';
  if (field.startsWith('storage')) return 'storage';
  if (field.startsWith('networking')) return 'networking';
  if (field.startsWith('readiness') || field.startsWith('liveness')) return 'health';
  return 'summary';
}

export function errorsForStep(errors: Errors, step: DeployStep): Errors {
  const out: Errors = {};
  for (const [k, v] of Object.entries(errors)) if (stepOf(k) === step) out[k] = v;
  return out;
}

/** Maps backend 422 validation errors ({field, message}) onto spec field paths. */
export function mapServerErrors(errors: { field?: string; message?: string }[] | undefined): Record<string, string> {
  const out: Record<string, string> = {};
  for (const e of errors ?? []) {
    const f = (e.field ?? '').replace(/^body\.?/, '');
    if (f) out[f] = e.message ?? '';
  }
  return out;
}

export interface ImageConfig {
  exposedPorts: { port: number; protocol: string }[];
  volumes: string[];
  user: string;
  runsAsRoot: boolean;
  env: { name: string; value: string }[];
  healthcheck?: string[] | null;
}

export interface OnboardingChoice {
  image: string; // full reference incl. tag
  name: string;
  namespace: string;
  replicas: number;
  port: number | null;
  storage: boolean;
  mountPath: string;
  probe: ProbeType;
  probePath: string;
}

/** Suggestions for the destination step, derived from the image configuration. */
export function suggestDestination(image: string, cfg: ImageConfig | null): OnboardingChoice {
  const port = cfg?.exposedPorts?.[0]?.port ?? null;
  const tcp = cfg?.exposedPorts?.[0]?.protocol === 'UDP' ? false : true;
  return {
    image,
    name: sanitizeName(repoBasename(image)),
    namespace: 'default',
    replicas: 2,
    port,
    storage: !!cfg?.volumes?.length,
    mountPath: cfg?.volumes?.[0] ?? '/data',
    probe: port && tcp ? 'tcp' : 'none',
    probePath: '/',
  };
}

/** Onboarding → deploy wizard prefill. */
export function choiceToSpec(c: OnboardingChoice, cfg: ImageConfig | null): DeploySpec {
  const s = defaultSpec();
  const { image, tag } = splitImage(c.image);
  s.name = c.name;
  s.namespace = c.namespace;
  s.image = image;
  s.tag = tag || 'latest';
  s.replicas = c.replicas;
  s.port = c.port;
  const proto = cfg?.exposedPorts?.find((p) => p.port === c.port)?.protocol;
  s.protocol = proto === 'UDP' ? 'UDP' : 'TCP';
  s.networking.service_type = c.port ? 'ClusterIP' : 'none';
  if (c.storage) {
    s.storage.enabled = true;
    s.storage.mount_path = c.mountPath && c.mountPath !== '/' ? c.mountPath : '/data';
  }
  if (c.port && c.probe !== 'none') {
    s.readiness = { ...emptyProbe(), type: c.probe, path: c.probePath || '/' };
    s.liveness = { ...emptyProbe(), type: c.probe, path: c.probePath || '/', initial_delay: 15, period: 20 };
  }
  return s;
}

/** Merge a (possibly partial) prefill object into a full spec. */
export function mergeSpec(base: DeploySpec, prefill: Partial<DeploySpec> | null | undefined): DeploySpec {
  if (!prefill) return base;
  return {
    ...base,
    ...prefill,
    storage: { ...base.storage, ...(prefill.storage ?? {}) },
    networking: {
      ...base.networking,
      ...(prefill.networking ?? {}),
      ingress: { ...base.networking.ingress, ...(prefill.networking?.ingress ?? {}) },
    },
    readiness: { ...base.readiness, ...(prefill.readiness ?? {}) },
    liveness: { ...base.liveness, ...(prefill.liveness ?? {}) },
    env: prefill.env ?? base.env,
  };
}

/** Request body: empty strings become null (as the backend expects). */
export function toPayload(s: DeploySpec): DeploySpec {
  const nz = (v: string | null) => (v && v.trim() ? v.trim() : null);
  return {
    ...s,
    image: s.image.trim(),
    tag: s.tag.trim(),
    image_pull_secret: nz(s.image_pull_secret),
    cpu_request: nz(s.cpu_request),
    cpu_limit: nz(s.cpu_limit),
    memory_request: nz(s.memory_request),
    memory_limit: nz(s.memory_limit),
    storage: { ...s.storage, storage_class: nz(s.storage.storage_class) },
    networking: {
      ...s.networking,
      ingress: { ...s.networking.ingress, host: s.networking.ingress.host.trim().toLowerCase(), class_name: nz(s.networking.ingress.class_name), tls_secret: nz(s.networking.ingress.tls_secret) },
    },
  };
}

/** Parse multi-document YAML headers (kind/name/namespace) for the Apply YAML page without full validation. */
export interface DocHeader {
  apiVersion?: string;
  kind?: string;
  name?: string;
  namespace?: string;
}
