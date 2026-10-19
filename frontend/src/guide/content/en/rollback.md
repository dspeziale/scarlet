---
title: Rollback
summary: Quickly return to a previous, working version of an application.
category: reliability
order: 30
keywords: rollback, undo, revision, rollout history, restore version
related: rolling-update, deployment, replicaset, proc-rollback, proc-gestione-incidenti
---

## In simple terms

A **rollback** is an application's "undo". If you have just published a new version and something is wrong (errors, crashes, slowness), a rollback makes Kubernetes bring the Pods back to the configuration of a previous revision, using the same gradual mechanism as a [rolling update](guide:rolling-update).

It is often the fastest way to restore service: restore first, investigate calmly afterwards.

## Technical details

- Every change to a Deployment's `spec.template` creates a **revision**, i.e. a ReplicaSet with the `deployment.kubernetes.io/revision` annotation.
- A rollback copies the template of the chosen ReplicaSet into the Deployment. The result is a **new** revision with a higher number (the source revision disappears from the list because it gets "promoted").
- Only revisions that are still retained are available (`spec.revisionHistoryLimit`, default 10). With `revisionHistoryLimit: 0` rollback is impossible.
- A rollback only covers the **Pod template**. It does not restore:
  - the replica count;
  - referenced ConfigMaps and Secrets (if you changed them, their content stays the new one);
  - data on persistent volumes or database migrations already applied;
  - Services, Ingresses and other resources.
- StatefulSets and DaemonSets keep their history through `ControllerRevision` objects; `kubectl rollout undo` works for them too.
- If the Deployment is managed by GitOps (Argo CD, Flux) a manual rollback will be overwritten: roll back in the repository instead.

## Example

Shell alternative (for administrators):

```bash
# List revisions
kubectl -n shop rollout history deployment/web

# Show one revision
kubectl -n shop rollout history deployment/web --revision=7

# Go back to the previous revision or to a specific one
kubectl -n shop rollout undo deployment/web
kubectl -n shop rollout undo deployment/web --to-revision=7

kubectl -n shop rollout status deployment/web
```

To keep the history readable, record the reason for each change:

```bash
kubectl -n shop annotate deployment/web kubernetes.io/change-cause="web 1.5.0: new checkout"
```

## What can go wrong

- **No revision available**: history was pruned or the workload was recreated from scratch.
- **Ineffective rollback**: the problem was in a ConfigMap, a Secret or the database, not in the image.
- **Irreversible migrations**: the old version is not compatible with the updated data schema.
- **Image no longer available** in the registry (tag deleted): restored Pods go into `ImagePullBackOff`.
- **Overwritten** by CI/CD or GitOps pipelines.

## How to verify

- [Operazioni → Rollout](app:/operations/rollout) shows the current revision, the list of revisions and the progress.
- In the Deployment **YAML** tab check the effective image; the **Eventi** tab shows the ReplicaSet scaling.
- Check that all replicas are ready and that the [Centro Operativo](app:/operations-center) no longer reports errors.
- Every rollback performed through the application is recorded in the [Audit Log](app:/security/audit).

## How to fix

1. Follow the [Perform a rollback](guide:proc-rollback) procedure: pick the working revision, confirm and wait for completion.
2. If the rollback does not help, check changes to ConfigMaps/Secrets and restore them from the **YAML** tab or from the manifests export.
3. After restoring service, analyze the faulty version in a test environment before publishing it again.
4. Document what happened following [Incident management](guide:proc-gestione-incidenti).
