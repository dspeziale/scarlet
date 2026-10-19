import {
  Activity,
  BookOpen,
  Boxes,
  Container,
  Gauge,
  LayoutDashboard,
  Network,
  Server,
  Settings,
  ShieldCheck,
  Siren,
  SlidersHorizontal,
  Database,
  Wrench,
  type LucideIcon,
} from 'lucide-react';

export interface NavItem {
  id: string;
  to: string;
  /** Required permission to show the entry (the backend enforces it anyway). */
  perm?: string;
}

export interface NavGroup {
  id: string;
  icon: LucideIcon;
  to?: string;
  items?: NavItem[];
  perm?: string;
}

// Labels are i18n keys: nav.<group id> and nav.<item id>.
export const NAV: NavGroup[] = [
  { id: 'dashboard', icon: LayoutDashboard, to: '/' },
  { id: 'operationsCenter', icon: Siren, to: '/operations-center' },
  {
    id: 'cluster',
    icon: Server,
    items: [
      { id: 'clusterOverview', to: '/cluster' },
      { id: 'nodes', to: '/cluster/nodes' },
      { id: 'namespaces', to: '/cluster/namespaces' },
      { id: 'events', to: '/cluster/events' },
    ],
  },
  {
    id: 'applications',
    icon: Boxes,
    items: [
      { id: 'pods', to: '/k8s/pods' },
      { id: 'deployments', to: '/k8s/deployments' },
      { id: 'statefulsets', to: '/k8s/statefulsets' },
      { id: 'daemonsets', to: '/k8s/daemonsets' },
      { id: 'jobs', to: '/k8s/jobs' },
      { id: 'cronjobs', to: '/k8s/cronjobs' },
    ],
  },
  {
    id: 'networking',
    icon: Network,
    items: [
      { id: 'services', to: '/k8s/services' },
      { id: 'ingresses', to: '/k8s/ingresses' },
      { id: 'endpoints', to: '/k8s/endpoints' },
    ],
  },
  {
    id: 'storage',
    icon: Database,
    items: [
      { id: 'persistentvolumes', to: '/k8s/persistentvolumes' },
      { id: 'persistentvolumeclaims', to: '/k8s/persistentvolumeclaims' },
      { id: 'storageclasses', to: '/k8s/storageclasses' },
    ],
  },
  {
    id: 'configuration',
    icon: SlidersHorizontal,
    items: [
      { id: 'configmaps', to: '/k8s/configmaps' },
      { id: 'secrets', to: '/k8s/secrets' },
    ],
  },
  {
    id: 'containers',
    icon: Container,
    items: [
      { id: 'podmanContainers', to: '/podman/containers', perm: 'podman.read' },
      { id: 'podmanImages', to: '/podman/images', perm: 'podman.read' },
      { id: 'podmanRegistries', to: '/podman/registries', perm: 'podman.read' },
    ],
  },
  {
    id: 'monitoring',
    icon: Gauge,
    items: [
      { id: 'cpu', to: '/monitoring/cpu' },
      { id: 'memory', to: '/monitoring/memory' },
      { id: 'monStorage', to: '/monitoring/storage' },
      { id: 'health', to: '/monitoring/health' },
      { id: 'ha', to: '/monitoring/ha' },
      { id: 'monEvents', to: '/monitoring/events' },
      { id: 'logs', to: '/monitoring/logs', perm: 'logs.read' },
    ],
  },
  {
    id: 'operations',
    icon: Wrench,
    items: [
      { id: 'onboarding', to: '/operations/onboarding', perm: 'workloads.deploy' },
      { id: 'deploy', to: '/operations/deploy', perm: 'workloads.deploy' },
      { id: 'scale', to: '/operations/scale' },
      { id: 'restart', to: '/operations/restart' },
      { id: 'rollout', to: '/operations/rollout' },
      { id: 'yaml', to: '/operations/yaml' },
      { id: 'backup', to: '/operations/backup', perm: 'backup.read' },
      { id: 'maintenance', to: '/operations/maintenance' },
    ],
  },
  {
    id: 'security',
    icon: ShieldCheck,
    items: [
      { id: 'users', to: '/security/users', perm: 'users.manage' },
      { id: 'roles', to: '/security/roles' },
      { id: 'permissions', to: '/security/permissions' },
      { id: 'audit', to: '/security/audit', perm: 'audit.read' },
    ],
  },
  { id: 'guide', icon: BookOpen, to: '/guide' },
  {
    id: 'settings',
    icon: Settings,
    perm: 'settings.read',
    items: [
      { id: 'setSystem', to: '/settings/system' },
      { id: 'setKubernetes', to: '/settings/kubernetes' },
      { id: 'setPodman', to: '/settings/podman' },
      { id: 'setLogging', to: '/settings/logging' },
      { id: 'setBackup', to: '/settings/backup' },
      { id: 'setAuth', to: '/settings/auth' },
    ],
  },
];

export const ACTIVITY_ICON = Activity;
