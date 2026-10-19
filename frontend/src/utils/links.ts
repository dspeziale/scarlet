// Kind -> URL key of the resource pages.
export const KIND_KEY: Record<string, string> = {
  Pod: 'pods',
  Deployment: 'deployments',
  ReplicaSet: 'replicasets',
  StatefulSet: 'statefulsets',
  DaemonSet: 'daemonsets',
  Job: 'jobs',
  CronJob: 'cronjobs',
  Service: 'services',
  Ingress: 'ingresses',
  Endpoints: 'endpoints',
  PersistentVolume: 'persistentvolumes',
  PersistentVolumeClaim: 'persistentvolumeclaims',
  StorageClass: 'storageclasses',
  ConfigMap: 'configmaps',
  Secret: 'secrets',
  Node: 'nodes',
  Namespace: 'namespaces',
  Event: 'events',
  PodDisruptionBudget: 'poddisruptionbudgets',
  HorizontalPodAutoscaler: 'horizontalpodautoscalers',
};

export function resourceLink(kind: string | null | undefined, namespace: string | null | undefined, name: string | null | undefined): string | null {
  if (!kind || !name) return null;
  const key = KIND_KEY[kind];
  if (!key) return null;
  return `/k8s/${key}/${encodeURIComponent(namespace || '_')}/${encodeURIComponent(name)}`;
}

export function listLink(kind: string, namespace?: string | null): string {
  const key = KIND_KEY[kind] ?? kind;
  return `/k8s/${key}${namespace ? `?namespace=${encodeURIComponent(namespace)}` : ''}`;
}
