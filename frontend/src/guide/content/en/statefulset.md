---
title: StatefulSet
summary: Runs applications with a stable identity and their own data, such as databases and message queues.
category: workloads
order: 30
keywords: statefulset, database, stable identity, volumeClaimTemplates, headless service, ordinal
related: deployment, persistent-volume-claim, storage-class, service, pod, backup
---

## In simple terms

A **StatefulSet** is similar to a [Deployment](guide:deployment), but designed for applications that **remember something**: databases, message brokers, clusters such as etcd or Elasticsearch. Each Pod has a **fixed name** (`db-0`, `db-1`, `db-2`) and a **disk of its own** that follows it even when it is recreated on another node.

If `db-1` dies, Kubernetes recreates exactly `db-1`, with the same name and the same volume. With a Deployment, instead, Pods are interchangeable and have random names.

## Technical details

- **Stable identity**: Pods are named `<name>-<ordinal>` with ordinals from 0 to N-1.
- **Stable DNS**: requires a *headless* [Service](guide:service) (`clusterIP: None`) referenced in `spec.serviceName`. Each Pod is reachable as `db-0.db.<namespace>.svc.cluster.local`.
- **Per-Pod storage**: `spec.volumeClaimTemplates` generates one [PVC](guide:persistent-volume-claim) per Pod, named `<template>-<name>-<ordinal>` (e.g. `data-db-0`). PVCs are **not deleted** when you scale down or delete the StatefulSet (unless a different `persistentVolumeClaimRetentionPolicy` is set).
- **Ordering**: with `podManagementPolicy: OrderedReady` (default) Pods are created in order 0→N-1, each only once the previous one is Ready, and removed in reverse order. `Parallel` removes this constraint.
- **Updates**: `updateStrategy.type: RollingUpdate` updates from the highest ordinal to the lowest; `rollingUpdate.partition` enables staged (canary) updates. `OnDelete` updates a Pod only when you delete it yourself.

In Scarlet: [Applicazioni → StatefulSets](app:/k8s/statefulsets). The Relazioni tab shows linked Pods and PVCs.

## Example

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: db
  namespace: shop
spec:
  serviceName: db
  replicas: 3
  selector:
    matchLabels: { app: db }
  template:
    metadata:
      labels: { app: db }
    spec:
      containers:
        - name: postgres
          image: docker.io/library/postgres:16
          ports: [{ containerPort: 5432 }]
          volumeMounts:
            - { name: data, mountPath: /var/lib/postgresql/data }
  volumeClaimTemplates:
    - metadata:
        name: data
      spec:
        accessModes: [ReadWriteOnce]
        storageClassName: standard
        resources:
          requests:
            storage: 20Gi
```

## What can go wrong

- **Pod stuck in [Pending](guide:pending)** because its PVC is Pending (no StorageClass, no available PV) or because the volume is bound to an unavailable zone/node.
- **Startup stuck halfway**: with `OrderedReady`, if `db-1` never becomes Ready, `db-2` is never created.
- **Failed node**: a StatefulSet Pod on a [NotReady](guide:node-notready) node stays `Terminating`/`Unknown` and Kubernetes does **not** create a copy elsewhere until it is sure the old one is dead, to avoid two instances writing to the same disk.
- **Data loss** if you manually delete PVCs thinking they are "garbage".

## How to verify

In Scarlet check ready replicas, then Pods and PVCs in the Relazioni tab; in [Storage → Persistent Volume Claims](app:/k8s/persistentvolumeclaims) verify that PVCs are `Bound`.

```bash
kubectl -n shop get statefulset db
kubectl -n shop get pods -l app=db -o wide
kubectl -n shop get pvc -l app=db
kubectl -n shop rollout status statefulset/db
```

## How to fix

1. If a PVC is Pending, fix storage first: see [Persistent Volume Claim](guide:persistent-volume-claim).
2. If a Pod does not become Ready, diagnose it like any Pod ([procedure](guide:proc-diagnosticare-pod)); the other ordinals wait.
3. If a node is permanently lost, an administrator can, after verifying the node is really powered off, force-delete the Pod (`kubectl delete pod db-1 --grace-period=0 --force`): this is a risky operation.
4. Before scaling down or deleting PVCs, take a [backup](guide:backup) of the application data: Scarlet does not save volume contents.
