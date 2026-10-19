---
title: Node maintenance
summary: How to safely empty a node with cordon and drain and bring it back into service with uncordon.
category: procedures
order: 110
keywords: maintenance, cordon, drain, uncordon, eviction, poddisruptionbudget, node, patch, reboot
related: node, alta-disponibilita, proc-verificare-nodo, daemonset, replica, scheduling
---

## When you need it

Before any intervention that makes a node unavailable: operating system update, reboot, kubelet upgrade, hardware replacement, VM migration. The goal is to move Pods to other nodes in an orderly way instead of letting them die abruptly.

## Prerequisites

- **Operator** or **Administrator** role.
- The other nodes have enough **free capacity** to host the moved Pods (check [Cluster → Nodes](app:/cluster/nodes) and requests).
- Critical applications have at least 2 [replicas](guide:replica) and, ideally, a PodDisruptionBudget (see [High availability](guide:alta-disponibilita)).
- You know which Pods use local storage (`emptyDir`, local volumes): `emptyDir` data is lost when the Pod is evicted.

## Procedure

1. **Verify the node** as described in [Verify a node](guide:proc-verificare-nodo) and note which Pods it hosts.
2. **Cordon.** In [Operations → Maintenance](app:/operations/maintenance) select the node and run **Cordon**. The node becomes `SchedulingDisabled`: existing Pods keep running, but no new ones arrive.
3. **Drain.** Run **Drain** on the same node. Scarlet:
   - evicts Pods through the **Eviction API**, so it respects **PodDisruptionBudgets**: if an eviction would violate a PDB it is refused and retried;
   - **skips DaemonSet Pods**, which by definition must stay on every node;
   - leaves it to the controllers (Deployment, StatefulSet, ReplicaSet) to recreate the Pods on other nodes.
4. **Follow the progress.** The drain completes when only DaemonSet Pods (and static Pods) remain on the node. If it gets stuck, read the reported reason (usually a PDB that allows no disruptions).
5. **Check the applications.** No new `Pending` Pods or degraded Deployments should appear in the [Operations Center](app:/operations-center).
6. **Perform the maintenance** on the node (outside Scarlet, for example via SSH): updates, reboot, etc.
7. **Wait for the node to be `Ready` again** in [Cluster → Nodes](app:/cluster/nodes).
8. **Uncordon.** Run **Uncordon** in [Maintenance](app:/operations/maintenance). The node becomes schedulable again.

Shell equivalents:

```bash
kubectl cordon worker-02
kubectl drain worker-02 --ignore-daemonsets --delete-emptydir-data --timeout=10m
# ... maintenance ...
kubectl uncordon worker-02
kubectl get pdb -A
```

Warning: `--delete-emptydir-data` accepts the loss of `emptyDir` data.

## Verification

- The node is `Ready` and no longer `SchedulingDisabled`.
- All Deployments have available replicas equal to the desired ones.
- No `Pending` Pods in the Operations Center.
- DaemonSet Pods on the node are `Running`.

Note: after uncordon Kubernetes does **not** automatically rebalance the Pods already moved. The node will fill up with new Pods created later; if needed, a controlled restart from [Operations → Restart](app:/operations/restart) redistributes a Deployment's Pods.

## If something goes wrong

- **Drain blocked by a PDB**: the budget allows no disruptions (for example `minAvailable` equal to the replica count, or not all replicas Ready). Temporarily increase replicas, or fix the non-Ready Pods. Do not delete the PDB without assessing the impact.
- **Pods not managed by a controller**: a "bare" Pod is not recreated elsewhere. It must be recreated manually or turned into a Deployment.
- **`Pending` Pods after the drain**: not enough capacity on other nodes, or constraints (nodeSelector, affinity, node-bound PVCs). Consider uncordoning and postponing the maintenance.
- **The node does not become `Ready`** after maintenance: follow [Node NotReady](guide:node-notready) and keep it cordoned until resolved.
