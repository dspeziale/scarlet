// Types of the backend responses used by the UI.

export type Health =
  | 'healthy'
  | 'progressing'
  | 'degraded'
  | 'failed'
  | 'pending'
  | 'completed'
  | 'suspended'
  | 'unknown';

export type Severity = 'CRITICAL' | 'ERROR' | 'WARNING' | 'INFO';
export type Role = 'admin' | 'operator' | 'viewer';

export interface User {
  id: number;
  username: string;
  display_name: string;
  email: string;
  role: Role;
  active: boolean;
  must_change_password: boolean;
  language: 'it' | 'en';
  last_login_at: string | null;
  created_at: string;
  locked: boolean;
}

export interface SessionInfo {
  user: User;
  permissions: string[];
  csrfToken: string;
  expiresAt: string;
}

export interface SystemInfo {
  appName: string;
  version: string;
  apiVersion: string;
  mode: 'live' | 'demo';
  environment: 'production' | 'development';
  setupRequired: boolean;
  languages: string[];
}

export interface ErrorInfo {
  code: string;
  message: string;
  details?: string | null;
  params?: Record<string, unknown>;
}

export interface SystemStatus {
  appName: string;
  version: string;
  apiVersion: string;
  mode: 'live' | 'demo';
  environment: string;
  kubernetes: { connected: boolean; context?: string; server?: string; version?: string; error?: ErrorInfo };
  podman: { connected: boolean; version?: string; apiVersion?: string; rootless?: boolean; endpoint?: string; error?: ErrorInfo };
  monitor: { at: number | null; error: string | null; issues: number };
  prometheus: boolean;
}

export interface KindInfo {
  key: string;
  kind: string;
  apiVersion: string;
  namespaced: boolean;
  category: string;
  guide: string | null;
  actions: string[];
  hasLogs: boolean;
  /** Operators may create/change it (workloads.deploy); other kinds need resources.apply. */
  workload: boolean;
}

export interface ContainerRow {
  name: string;
  image: string;
  ready: boolean;
  restarts: number;
  state: string;
  reason?: string | null;
  message?: string | null;
  exitCode?: number | null;
  lastState: Record<string, Record<string, unknown>>;
  ports: number[];
  requests: Record<string, string>;
  limits: Record<string, string>;
  readinessProbe: boolean;
  livenessProbe: boolean;
  startupProbe: boolean;
}

/** Summary of a resource: common fields + kind-specific fields. */
export interface ResourceSummary {
  kind: string;
  name: string;
  namespace: string | null;
  uid: string;
  createdAt: string | null;
  labels: Record<string, string>;
  health: Health;
  [key: string]: unknown;
}

export interface ResourceList {
  kind: KindInfo;
  items: ResourceSummary[];
  count: number;
}

export interface ResourceDetail {
  kind: KindInfo;
  summary: ResourceSummary;
  object: Record<string, unknown>;
  yaml: string;
}

export interface Check {
  id: string;
  status: 'ok' | 'fail' | 'warn' | 'unknown';
  params: Record<string, unknown>;
}

export interface Issue {
  id: string;
  severity: Severity;
  reason: string;
  kind: string;
  name: string;
  namespace: string | null;
  owner: { kind: string; name: string } | null;
  node: string | null;
  container: string | null;
  message: string;
  since: string | null;
  affected: string[];
  facts: Record<string, unknown>;
  checks: Check[];
  actions: string[];
  guide: string | null;
  likely_cause: string | null;
  acknowledged?: { by: string; at: string; notificationId: number } | null;
  notificationId?: number | null;
}

export interface Notification {
  id: number;
  fingerprint: string;
  severity: Severity;
  reason: string;
  source: string;
  resource_kind: string;
  resource_name: string;
  namespace: string;
  message: string;
  data: Record<string, unknown>;
  status: 'open' | 'acknowledged' | 'resolved';
  occurrences: number;
  first_seen: string;
  last_seen: string;
  acknowledged_by: string | null;
  acknowledged_at: string | null;
  resolved_at: string | null;
}

export interface NotificationCounts {
  open: number;
  acknowledged: number;
  bySeverity: Record<Severity, number>;
}

export interface Overview {
  cluster: { connected: boolean; context?: string; version?: { gitVersion?: string } | null; error?: ErrorInfo };
  partial: { kind: string; code: string; message: string }[];
  nodes: { total: number; ready: number; notReady: number; cordoned: number };
  namespaces: number;
  pods: { total: number; running: number; healthy: number; failed: number; pending: number; completed: number };
  deployments: { total: number; healthy: number; degraded: number; failed: number };
  statefulsets: { total: number; degraded: number };
  daemonsets: { total: number; degraded: number };
  services: number;
  resources: {
    allocatableCpu: number;
    allocatableMemory: number;
    requestedCpu: number;
    requestedMemory: number;
    usage: { cpu: number; memory: number } | null;
    metricsAvailable: boolean;
  };
  storage: { pvCount: number; pvCapacity: number; pvcBound: number; pvcPending: number; pvcTotal: number };
  restarts: { total: number; top: { name: string; namespace: string; restarts: number; status: string }[] };
  events: { warnings: number; recent: ResourceSummary[] };
  issues: { counts: Record<Severity, number>; top: Issue[] };
  notifications: NotificationCounts;
}

export interface GraphNode {
  id: string;
  kind: string;
  name: string;
  namespace: string | null;
  health: Health;
  missing: boolean;
  root?: boolean;
}
export interface Graph {
  nodes: GraphNode[];
  edges: { from: string; to: string; type: string }[];
}

export interface Operation {
  id: string;
  kind: string;
  target: string;
  user: string;
  status: 'running' | 'succeeded' | 'failed' | 'cancelled';
  startedAt: string;
  finishedAt: string | null;
  steps: { ts: string; step: string; [k: string]: unknown }[];
  result: unknown;
  error: ErrorInfo | null;
}

export interface HealthCheck {
  id: string;
  status: 'healthy' | 'degraded' | 'unhealthy';
  message: string;
  params: Record<string, unknown>;
  optional: boolean;
  latencyMs: number;
}
