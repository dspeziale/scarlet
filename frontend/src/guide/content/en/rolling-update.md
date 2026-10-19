---
title: Rolling update
summary: Progressive replacement of Pods without interrupting the service.
category: reliability
order: 20
keywords: rolling update, rollout, update, maxSurge, maxUnavailable, revision
related: deployment, replicaset, rollback, readiness-probe, proc-pubblicare-applicazione, proc-rollback
---

## In simple terms

When you update an application (for example you change the image version), Kubernetes does not switch everything off and on again: it replaces Pods **a few at a time**. It creates some new Pods, waits until they are ready, then removes some of the old ones, and so on. Users keep being served the whole time.

This process is called a **rolling update**; the overall operation is called a **rollout**.

## Technical details

- A rollout starts when the **Pod template** (`spec.template`) changes: image, environment variables, resources, template labels. Changing only `replicas` does not create a new rollout.
- The Deployment creates a **new ReplicaSet** (new revision) and scales it up while scaling the old one down. Old ReplicaSets are kept (at zero replicas) to allow a [rollback](guide:rollback); how many are kept depends on `spec.revisionHistoryLimit` (default 10).
- Parameters in `spec.strategy.rollingUpdate`:
  - `maxSurge`: how many Pods above `replicas` may exist during the update (default 25%).
  - `maxUnavailable`: how many Pods may be unavailable (default 25%).
- `minReadySeconds`: how many seconds a Pod must stay Ready before it counts as available.
- `progressDeadlineSeconds` (default 600): if the rollout makes no progress within this time, the `Progressing` condition becomes `False` with reason `ProgressDeadlineExceeded`. Kubernetes does **not** roll back automatically.
- The alternative `Recreate` strategy deletes all old Pods before creating the new ones (with downtime).
- StatefulSets update one Pod at a time in reverse ordinal order (`RollingUpdate`); DaemonSets update node by node according to their own `maxUnavailable`.
- A rolling update is only safe if the [readiness probe](guide:readiness-probe) is reliable: without a probe, a Pod is considered ready as soon as the container starts.

## Example

```yaml
spec:
  replicas: 4
  minReadySeconds: 10
  revisionHistoryLimit: 10
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 0
```

With `maxSurge: 1` and `maxUnavailable: 0` capacity never drops below 4 ready Pods.

Shell alternative:

```bash
kubectl -n shop set image deployment/web web=registry.example.com/shop/web:1.5.0
kubectl -n shop rollout status deployment/web
kubectl -n shop rollout history deployment/web
```

## What can go wrong

- **Stuck rollout**: new Pods end up in `ImagePullBackOff` or `CrashLoopBackOff`; with `maxUnavailable: 0` the old ones stay up and the service holds, but the update never completes.
- **New Pods Pending**: `maxSurge` needs extra capacity in the cluster.
- **Missing or too lenient readiness**: traffic reaches Pods that are not ready yet, causing 5xx errors during the update.
- **Version incompatibility**: old and new versions coexist for a few minutes (DB schema, APIs): the application must tolerate it.
- **`latest` tag**: changing the image behind the same tag does not trigger a rollout and makes it hard to know what is running.

## How to verify

- [Operazioni → Rollout](app:/operations/rollout) shows rollout status, revisions and pause/resume commands.
- In the Deployment detail, the **Eventi** tab shows the ReplicaSet scaling and the **Relazioni** tab shows the old and new ReplicaSets.
- The [Centro Operativo](app:/operations-center) flags failing Pods and degraded deployments.

## How to fix

1. If the rollout is stuck, open one of the new Pods and read **Eventi** and **Log** to find the cause.
2. If the problem is in the new version, perform a [rollback](guide:proc-rollback) from the Rollout page.
3. You can **pause** the rollout to investigate and **resume** it after the fix.
4. Fix the configuration (image, resources, probes) and apply again: a new revision will start.
