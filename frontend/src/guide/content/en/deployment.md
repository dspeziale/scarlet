---
title: Deployment
summary: Manages identical copies of your application and updates them progressively without downtime.
category: workloads
order: 10
keywords: deployment, replicaset, rolling update, replicas, rollout, revision
related: replicaset, pod, replica, rolling-update, rollback, readiness-probe, proc-pubblicare-applicazione, proc-scalare
---

## In simple terms

A **Deployment** is the standard way to run a *stateless* application (one that keeps no data of its own) on Kubernetes. You declare "I want 3 copies of this image, with these resources" and Kubernetes creates them, recreates them if they die and updates them one at a time when you change version.

You do not create Pods by hand: the Deployment creates them through an intermediate object called a [ReplicaSet](guide:replicaset). If you delete a Pod managed by a Deployment, a new one appears immediately: that is intended behavior, not an error.

## Technical details

- `spec.replicas`: desired number of Pods.
- `spec.selector.matchLabels`: the labels that identify the managed Pods. It must match `spec.template.metadata.labels` and is **immutable** after creation.
- `spec.template`: the Pod template (containers, image, ports, probes, resources). Every change to the template produces a new **revision** and a new ReplicaSet; changing only `replicas` does not.
- `spec.strategy`: `RollingUpdate` (default, with `maxSurge` and `maxUnavailable`, default 25%) or `Recreate` (stops all Pods, then creates the new ones: there is downtime).
- `spec.revisionHistoryLimit` (default 10): how many old ReplicaSets are kept for [rollback](guide:rollback).
- `spec.progressDeadlineSeconds` (default 600): after this time without progress the `Progressing` condition becomes `False` with reason `ProgressDeadlineExceeded`. The rollout is not undone automatically: someone must act.

Status is in `status`: `replicas`, `updatedReplicas`, `readyReplicas`, `availableReplicas` and the `Available` and `Progressing` conditions. A Pod counts as "ready" only when its [readiness probe](guide:readiness-probe) succeeds.

In Scarlet the list is under [Applicazioni → Deployments](app:/k8s/deployments); the detail page shows ready/desired replicas, linked ReplicaSets (Relazioni tab), events and YAML.

## Example

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: web
  namespace: shop
spec:
  replicas: 3
  selector:
    matchLabels:
      app: web
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 0
  template:
    metadata:
      labels:
        app: web
    spec:
      containers:
        - name: web
          image: registry.example.com/shop/web:1.4.2
          ports:
            - containerPort: 8080
          resources:
            requests: { cpu: 100m, memory: 128Mi }
            limits: { memory: 256Mi }
          readinessProbe:
            httpGet: { path: /healthz, port: 8080 }
```

## What can go wrong

- **Degraded Deployment**: `readyReplicas` is lower than `replicas`. The [Centro Operativo](app:/operations-center) flags it automatically.
- **Stuck rollout**: the new version never becomes ready (wrong image, failing probe, crash at startup). With `maxUnavailable: 0` the old Pods stay up, so service continues, but the update does not progress.
- **Pods in [CrashLoopBackOff](guide:crashloopbackoff) or [ImagePullBackOff](guide:imagepullbackoff)** after an image or tag change.
- **Inconsistent selector**: if the template labels do not match the selector, the API rejects the object.
- **[Pending](guide:pending) Pods**: resource requests too high for the available nodes.

## How to verify

In Scarlet: open the Deployment, check ready/desired replicas and the Eventi tab; the [Operazioni → Rollout](app:/operations/rollout) page shows the status of the update in progress.

From a shell (admin alternative):

```bash
kubectl -n shop get deployment web
kubectl -n shop rollout status deployment/web
kubectl -n shop describe deployment web
kubectl -n shop get rs,pods -l app=web
```

## How to fix

1. Read the events of the Deployment and of the newest Pods: they almost always point to the cause.
2. If the new version is faulty, perform a [rollback](guide:rollback) from the Rollout page (equivalent: `kubectl -n shop rollout undo deployment/web`).
3. If resources are short, lower the requests or add capacity to the cluster; see [Pending](guide:pending).
4. To change the number of copies use [Operazioni → Scale](app:/operations/scale) (procedure: [Scale an application](guide:proc-scalare)).
5. Fix the manifest in the YAML tab, validate it with the server-side dry-run, review the diff and apply: the Deployment will start a new rollout.
