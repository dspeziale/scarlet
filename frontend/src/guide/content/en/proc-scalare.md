---
title: Scaling an application
summary: Increase or decrease the number of replicas of a Deployment or StatefulSet in a controlled way.
category: procedures
order: 60
keywords: scale, scaling, replicas, deployment, statefulset, capacity, hpa
related: replica, deployment, statefulset, resource-request, alta-disponibilita, pending
---

## When you need it

- Increase replicas to handle more load or to get redundancy (at least 2 for important services).
- Reduce them to free resources, for example in test environments.
- Temporarily set them to `0` to stop an application without deleting it (for example before working on the database it uses).

## Prerequisites

- **Operator** or **Administrator** role.
- Available capacity in the cluster: each new replica needs its own CPU and memory **requests**. Check [Monitoraggio → CPU](app:/monitoring/cpu) and [Memoria](app:/monitoring/memory).
- Knowing whether the workload has a **HorizontalPodAutoscaler** (HPA): if so, the HPA recomputes replicas and will undo your manual change. You must change the HPA minimum/maximum instead.

## Procedure

1. Open [Operazioni → Scale](app:/operations/scale) (or the Scale button on the Deployment or StatefulSet page).
2. Select namespace and workload. The current desired and ready replicas are shown next to it.
3. Enter the new number of replicas. For large changes go step by step (e.g. from 2 to 4, then 8) so you do not saturate nodes, databases or downstream services.
4. Confirm. The operation is recorded in the Audit Log.
5. Remember that scaling here changes the cluster, not the manifest in your repository: if you use GitOps or pipelines, update `spec.replicas` there too, otherwise the next deploy will restore the previous value.

Notes on workload types:

- **Deployment**: replicas are interchangeable; scale-up and scale-down are immediate.
- **StatefulSet**: Pods are created in order (`name-0`, `name-1`, ...) and removed in reverse order. Scaling down does **not** delete the PVCs of removed Pods. For clustered databases, first check that the application supports the new size.
- **DaemonSet**: cannot be scaled; it runs one Pod per eligible node.

Shell equivalent:

```bash
kubectl -n production scale deployment/orders-api --replicas=4
kubectl -n production rollout status deployment/orders-api
kubectl -n production get hpa
```

## Verification

- On the workload page ready replicas reach the desired value (e.g. `4/4`).
- The new Pods are **Running** and **Ready**, ideally on different nodes ([Alta affidabilità](app:/monitoring/ha)).
- In [Endpoints](app:/k8s/endpoints) the Service lists the new number of addresses.
- After a few minutes, per-Pod CPU and memory usage drops as expected (if metrics-server is available).

## If something goes wrong

- **New Pods stuck in Pending**: there is no room on the nodes for the requested resources, or affinity/taint constraints prevent it. Read the `FailedScheduling` events and see [Pending](guide:pending). Reduce replicas or add capacity.
- **Replicas go back to the previous value**: an HPA or a GitOps system is reconciling the state.
- **Scale-down and users see errors**: in-flight requests are cut off if the application does not handle `SIGTERM`; configure graceful shutdown and a readiness probe.
- **Pods getting OOMKilled after scale-down**: the remaining replicas receive more load; see [OOMKilled](guide:oomkilled).
