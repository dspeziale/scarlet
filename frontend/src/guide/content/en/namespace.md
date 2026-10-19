---
title: Namespace
summary: A logical space that separates cluster resources by team, environment or application.
category: concepts
order: 30
keywords: namespace, isolation, resourcequota, limitrange, rbac, terminating
related: cluster, pod, resource-request, resource-limit, networking, secret
---

## In simple terms

A namespace is like a folder inside the cluster. It keeps the resources of different applications, teams or environments separate: for example `production`, `staging`, `monitoring`. Two Deployments can share the same name if they live in different namespaces.

In Scarlet almost every list has a namespace filter: setting it correctly is the first step to avoid confusion (and to avoid acting on the wrong resource).

## Technical details

- **Namespaced** resources (Pod, Deployment, Service, ConfigMap, Secret, PVC, Role...) belong to exactly one namespace. **Cluster-scoped** ones (Node, PersistentVolume, StorageClass, ClusterRole, Namespace itself) do not.
- System namespaces: `default`, `kube-system` (cluster components), `kube-public`, `kube-node-lease` (node heartbeats). Do not deploy applications into `kube-system`.
- **RBAC**: a Role with a RoleBinding grants permissions only inside a namespace; a ClusterRole can be bound to one namespace with a RoleBinding.
- **ResourceQuota**: caps total CPU, memory and number of objects in a namespace. If a CPU/memory quota exists, every pod must declare requests and limits, otherwise creation is rejected.
- **LimitRange**: sets defaults and min/max values for container requests and limits.
- **DNS**: a Service is reachable as `<service>.<namespace>.svc.cluster.local`; within the same namespace `<service>` is enough.
- A namespace is **not a network boundary**: without NetworkPolicies, pods in different namespaces talk to each other freely.
- Deleting a namespace deletes **everything** in it. The namespace stays `Terminating` until all objects and their finalizers are gone.

## Example

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: staging
  labels:
    environment: staging
---
apiVersion: v1
kind: ResourceQuota
metadata:
  name: staging-quota
  namespace: staging
spec:
  hard:
    requests.cpu: "4"
    requests.memory: 8Gi
    limits.memory: 16Gi
    pods: "40"
```

```bash
# Shell alternative
kubectl get namespaces
kubectl get all -n staging
kubectl describe resourcequota -n staging
```

## What can go wrong

- **Wrong namespace**: the resource "does not exist" only because the filter points elsewhere.
- **Quota exceeded**: `exceeded quota` error when pods are created; the Deployment looks degraded but the pods do not even appear (the error is in the ReplicaSet events).
- **Pod rejected for missing requests** when a CPU/memory ResourceQuota exists.
- **Namespace stuck in Terminating**: some object has a finalizer that is never removed (often from a controller that is no longer installed).
- **Accidental deletion** of a namespace: loss of all its resources, and of data if PVs have the Delete reclaim policy.

## How to verify

- [Cluster → Namespace](app:/cluster/namespaces): list, status, resource count, quotas.
- Namespace detail: **Eventi** and **Relazioni** show what it contains.
- [Cluster events](app:/cluster/events) filtered by namespace, looking for `FailedCreate` or `exceeded quota`.

## How to fix

- Quota exceeded: reduce replicas or requests, or ask the administrator to raise the quota.
- Missing requests: add `resources.requests` and `resources.limits` to containers (see [Resource request](guide:resource-request)) or ask for a LimitRange with defaults.
- Namespace in Terminating: find the remaining objects (`kubectl api-resources --verbs=list --namespaced -o name | xargs -n1 kubectl get -n <ns> --ignore-not-found`) and fix the controller responsible for the finalizer. Removing finalizers by hand is the last resort.
- Before deleting a namespace, export its manifests from [Operazioni → Backup](app:/operations/backup).
