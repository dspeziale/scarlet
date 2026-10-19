---
title: Perform a rollback
summary: How to bring a Deployment back to a previous revision when an update causes problems.
category: procedures
order: 100
keywords: rollback, rollout, revision, undo, deployment, restore version
related: rollback, rolling-update, deployment, replicaset, proc-diagnosticare-pod, proc-gestione-incidenti
---

## When you need it

After an update (new image, new variables, new resources) the application gets worse: new Pods go into `CrashLoopBackOff` or `ImagePullBackOff`, the rollout does not progress, errors or latency increase. Rollback is the fastest way to return to a known, working version, even before you have understood the cause.

> A rollback restores the **Pod template** (image, variables, probes, resources). It does not restore data in volumes, database schemas, or ConfigMaps and Secrets changed separately.

## Prerequisites

- **Operator** or **Administrator** role.
- The resource is a Deployment (or a DaemonSet/StatefulSet, which also keep a revision history).
- A previous revision exists: Kubernetes keeps old ReplicaSets according to `spec.revisionHistoryLimit` (default 10). If it is set to 0 there is nothing to go back to.

## Procedure

1. **Check the situation.** Open [Operations → Rollout](app:/operations/rollout) and select namespace and Deployment. The status shows updated, available and unavailable replicas and whether the rollout is in progress, complete or stuck (`ProgressDeadlineExceeded`).
2. **If the rollout is still in progress, pause it** with **Pause**: this prevents more Pods from being replaced while you decide.
3. **Review the history.** Each entry in the revision list shows revision number, image and date. Identify the last working revision (usually the one right before the current).
4. **Compare.** If available, look at the difference between the current and the chosen revision to be sure what will change.
5. **Run the rollback.** Select the revision and confirm **Rollback**. If the Deployment was paused, then use **Resume**: a paused Deployment does not apply template changes.
6. **Follow the progress.** A rollback is itself a rolling update: Pods of the chosen revision progressively replace the faulty ones, respecting `maxUnavailable` and `maxSurge`.
7. **Record the intervention.** The action is tracked in the [Audit Log](app:/security/audit). Mark the problem as handled in the Notification Center and note the cause for whoever has to fix the new version.

Shell equivalents:

```bash
kubectl -n shop rollout status deployment/web
kubectl -n shop rollout history deployment/web
kubectl -n shop rollout history deployment/web --revision=7
kubectl -n shop rollout undo deployment/web --to-revision=7
```

Note: after the rollback the restored revision gets a **new number** (for example 7 becomes 9). This is normal Kubernetes behavior.

## Verification

- In [Rollout](app:/operations/rollout) the status is complete and all replicas are updated and available.
- In the Deployment detail the image is the expected one.
- Pods are `Running` and `Ready`, with no growing restart count.
- The problem disappears from the [Operations Center](app:/operations-center).
- The application responds correctly (check with your usual functional test).

## If something goes wrong

- **No revision available**: the history is empty or `revisionHistoryLimit` is too low. Restore the previous image manually from the YAML tab or from [Operations → Deploy](app:/operations/deploy).
- **The rollback does not start**: the Deployment is paused. Press **Resume**.
- **The previous revision fails too**: the cause is not in the template but outside it (ConfigMap, Secret, database, node, registry). Follow [Diagnose a Pod](guide:proc-diagnosticare-pod).
- **The rollout stays stuck**: check for `Pending` Pods due to insufficient resources or overly strict PodDisruptionBudgets.
- **Incompatible data**: if the new version migrated the database, the old one may not work. In that case you need the application's restore plan, not just a Kubernetes rollback.
