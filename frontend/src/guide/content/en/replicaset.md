---
title: ReplicaSet
summary: Ensures that the requested number of identical Pods is always running.
category: workloads
order: 20
keywords: replicaset, replicas, selector, owner reference, revision
related: deployment, pod, replica, rolling-update, rollback
---

## In simple terms

A **ReplicaSet** is a "counter with hands": it watches how many Pods with certain labels exist and, if there are fewer than expected, creates more; if there are too many, it deletes some. That is all.

In daily practice **you almost never create a ReplicaSet by hand**: a [Deployment](guide:deployment) creates and manages it. Every version of the Deployment corresponds to a different ReplicaSet; during an update the new ReplicaSet grows while the old one shrinks.

## Technical details

- `spec.replicas`, `spec.selector` and `spec.template` have the same meaning as in the Deployment.
- The ReplicaSet controller "adopts" any Pod that matches the selector and has no owner yet. This is why two workloads with overlapping selectors fight over Pods: avoid it.
- Each created Pod has a `metadata.ownerReferences` entry pointing to the ReplicaSet, which in turn points to the Deployment. PKM uses these relationships in the **Relazioni** tab of the detail page.
- The ReplicaSet name is `<deployment>-<pod-template-hash>`; the `pod-template-hash` label is added to Pods to tell versions apart.
- The `deployment.kubernetes.io/revision` annotation holds the revision number used by [rollback](guide:rollback).
- Editing the template of a ReplicaSet managed by a Deployment is pointless: the Deployment reverts it to the declared state. A ReplicaSet does not update existing Pods when its template changes: it applies only to new ones.

Old ReplicaSets remain with `replicas: 0` (up to `revisionHistoryLimit`) and consume no resources.

## Example

List the ReplicaSets of a Deployment and their revisions (shell alternative):

```bash
kubectl -n shop get rs -l app=web
# NAME             DESIRED   CURRENT   READY   AGE
# web-7d9c6b8f5c   3         3         3       2d
# web-5f4b7c9d8a   0         0         0       9d
kubectl -n shop rollout history deployment/web
```

## What can go wrong

- **DESIRED differs from READY** for a long time: Pods do not start or do not pass readiness. The cause is in the Pods, not in the ReplicaSet.
- **Two active ReplicaSets with replicas > 0** for a long time: a rollout is stuck halfway.
- **Orphan ReplicaSets** (no owning Deployment) created by old manifests or by deletions with `--cascade=orphan`: they keep running Pods nobody manages.
- **Namespace quota exceeded**: a `FailedCreate` event on the ReplicaSet means Pods cannot be created (for example because of a ResourceQuota).

## How to verify

In PKM open the Deployment, **Relazioni** tab, and select the ReplicaSet: you see desired/current/ready replicas and its events. Look for `FailedCreate` events.

```bash
kubectl -n shop describe rs web-7d9c6b8f5c
kubectl -n shop get events --field-selector involvedObject.name=web-7d9c6b8f5c
```

## How to fix

1. If the event is `FailedCreate`, read the message: quota, permissions or an admission webhook rejecting the Pod.
2. If Pods exist but are not ready, move to Pod diagnostics: [Diagnose a Pod](guide:proc-diagnosticare-pod).
3. If a rollout is stuck with two active ReplicaSets, consider a [rollback](guide:rollback) from the [Rollout](app:/operations/rollout) page.
4. Delete orphan ReplicaSets only after verifying that no service depends on their Pods.
5. Do not edit managed ReplicaSets: always act on the Deployment.
