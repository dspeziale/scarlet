---
title: Scheduling
summary: How Kubernetes chooses the node on which each pod runs, and why sometimes it finds none.
category: concepts
order: 60
keywords: scheduling, scheduler, affinity, taint, toleration, nodeselector, failedscheduling, topology spread
related: node, pod, pending, resource-request, alta-disponibilita, proc-manutenzione-nodo
---

## In simple terms

When a new pod is created, someone has to decide which node to put it on: that is the job of the **scheduler**. The scheduler discards unsuitable nodes (not enough free CPU or memory, rules that forbid it) and picks the best one among those left.

If no node fits, the pod stays [Pending](guide:pending) and a `FailedScheduling` event explains why. Reading that message carefully solves most cases.

## Technical details

The scheduler (`kube-scheduler`) works in two phases:

1. **Filtering**: removes unsuitable nodes. Main checks:
   - **Resources**: the sum of the [requests](guide:resource-request) of the pods already on the node plus those of the new pod must fit within `allocatable`. Requests count, not actual usage.
   - **nodeSelector** and **nodeAffinity** (`requiredDuringSchedulingIgnoredDuringExecution`): the node must carry certain labels.
   - **Taints and tolerations**: a node with a `NoSchedule` taint only accepts pods with the matching toleration. Control plane nodes usually have `node-role.kubernetes.io/control-plane:NoSchedule`.
   - **Unschedulable** (cordoned) or not ready node.
   - **Volumes**: a PVC with a zonal or local volume binds the pod to nodes that can mount it.
   - **Required podAntiAffinity**: for example "never two replicas on the same node".
2. **Scoring**: ranks the suitable nodes (resource balance, preferred affinities, `topologySpreadConstraints`, image already present) and picks the highest score.

The result is written to `spec.nodeName`. Once bound, a pod is **never moved again** by the scheduler, even if the rules change ("IgnoredDuringExecution"). It moves only if it is evicted or deleted and recreated.

With **PriorityClasses**, a high-priority pod can trigger **preemption** (eviction) of lower-priority pods to make room.

## Example

Spread replicas across different nodes and tolerate dedicated nodes:

```yaml
spec:
  topologySpreadConstraints:
    - maxSkew: 1
      topologyKey: kubernetes.io/hostname
      whenUnsatisfiable: ScheduleAnyway
      labelSelector:
        matchLabels:
          app: orders
  nodeSelector:
    kubernetes.io/os: linux
  tolerations:
    - key: dedicated
      operator: Equal
      value: batch
      effect: NoSchedule
```

Typical error message:

```text
0/4 nodes are available: 1 node(s) had untolerated taint {node-role.kubernetes.io/control-plane: },
3 Insufficient memory. preemption: 0/4 nodes are available
```

```bash
# Shell alternative
kubectl get events -n orders --field-selector reason=FailedScheduling
kubectl describe node worker-01 | grep -A8 "Allocated resources"
kubectl get nodes -o custom-columns=NAME:.metadata.name,TAINTS:.spec.taints
```

## What can go wrong

- **Insufficient cpu / memory**: requests are too high compared with the free space (not actual usage).
- **Untolerated taints**: reserved nodes or nodes in not-ready state.
- **Impossible affinity or nodeSelector**: labels no node has (often a typo).
- **Volume node affinity conflict**: the PV is in a different zone or on a different node.
- **Required anti-affinity** with more replicas than nodes.
- After a drain, pods that cannot find room elsewhere.

## How to verify

- Detail of the Pending pod, **Eventi** tab: the `FailedScheduling` message lists the reasons for each group of nodes.
- [Cluster → Nodi](app:/cluster/nodes): status, taints, schedulability, allocated resources.
- [Monitoraggio → Alta affidabilità](app:/monitoring/ha) to see how replicas are distributed.

## How to fix

- Insufficient resources: reduce requests if oversized, free capacity or add nodes.
- Taints: add the toleration only if the pod really must run on those nodes; if the node is cordoned after maintenance, uncordon it from [Operazioni → Manutenzione](app:/operations/maintenance).
- Affinity/nodeSelector: fix the labels in the YAML (**YAML** tab, with dry-run and diff before applying).
- Anti-affinity: switch from `required` to `preferred`, or use `topologySpreadConstraints` with `ScheduleAnyway`.
