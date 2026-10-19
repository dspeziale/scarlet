---
title: Pod in Pending
summary: The pod has been created but is not running yet, usually because no node can host it.
category: troubleshooting
order: 50
keywords: pending, failedscheduling, scheduling, insufficient resources, taint, affinity, pvc pending, unschedulable
related: scheduling, resource-request, node, persistent-volume-claim, storage-class, troubleshooting
---

## In simple terms

A pod in **Pending** has been accepted by the cluster but has not started yet. In most cases the [scheduler](guide:scheduling) cannot find a suitable node: the requested resources are too large, the available nodes have restrictions (taints) the pod does not tolerate, or the pod is waiting for a volume that is not yet available. Less often the pod is already assigned to a node but is still pulling the image.

A short Pending (a few seconds) is normal. A Pending that lasts minutes is a problem to investigate.

## Technical details

- If `spec.nodeName` is empty, the pod has not been scheduled: the `PodScheduled` condition is `False` with `reason: Unschedulable` and there is a `FailedScheduling` event.
- The `FailedScheduling` message summarizes why each node was discarded, for example:
  `0/3 nodes are available: 1 node(s) had untolerated taint {node-role.kubernetes.io/control-plane: }, 2 Insufficient memory.`
- Main causes:
  - **Insufficient cpu/memory**: the sum of the `requests` of the pods on the node plus those of the new pod exceeds the node `allocatable`. Requests count, not actual usage.
  - **Untolerated taints**: nodes with `NoSchedule` (control plane, dedicated nodes, cordoned nodes with `node.kubernetes.io/unschedulable`).
  - **nodeSelector / affinity** that no node satisfies, or overly strict anti-affinity.
  - **Unbound PVC**: `pod has unbound immediate PersistentVolumeClaims`. With `volumeBindingMode: WaitForFirstConsumer` the volume is created only after the node is chosen.
  - **Quotas**: a ResourceQuota prevents pod creation (in this case the pod is often not created at all and the error is on the ReplicaSet).
- If `nodeName` is set but the pod is still Pending, the problem is on the node: image pull in progress, volume mount, init containers running.

## Example

```bash
kubectl get pod db-0 -n shop
# NAME   READY   STATUS    RESTARTS   AGE
# db-0   0/1     Pending   0          7m

kubectl describe pod db-0 -n shop | sed -n '/Events/,$p'
#  Warning  FailedScheduling  default-scheduler  0/3 nodes are available:
#  3 node(s) didn't find available persistent volumes to bind.

kubectl get pvc -n shop
kubectl describe nodes | grep -A8 "Allocated resources"
```

## What can go wrong

- Requests were copied from another environment and are too high for this cluster.
- All worker nodes are cordoned after maintenance and nobody ran uncordon.
- The StorageClass does not exist, has no working provisioner, or there is no default StorageClass.
- A DaemonSet or another workload consumed the allocatable resources.
- An anti-affinity rule requires more nodes than available (for example 4 replicas with required anti-affinity on 3 nodes).

## How to verify

1. In the [Operations Center](app:/operations-center) Pending pods and Pending PVCs are reported separately.
2. Open the pod and read the **Eventi**: the `FailedScheduling` message tells how many nodes were discarded and why.
3. In the **Diagnostica** tab Scarlet summarizes the likely cause.
4. Check the nodes in [Cluster → Nodi](app:/cluster/nodes): status, schedulability (cordon) and allocated resources.
5. If there is a volume, check the PVC in [Storage → Persistent Volume Claims](app:/k8s/persistentvolumeclaims) and the [StorageClass](app:/k8s/storageclasses).

## How to fix

1. **Insufficient resources**: lower the `requests` if oversized, reduce replicas of less important workloads, or add nodes.
2. **Cordoned nodes**: if maintenance is over, uncordon from [Operazioni → Manutenzione](app:/operations/maintenance).
3. **Taints/affinity**: fix `nodeSelector`, `affinity` or add the correct `toleration` in the **YAML** tab, validating with the dry-run.
4. **Pending PVC**: check the StorageClass and provisioner; see [Persistent Volume Claim](guide:persistent-volume-claim).
5. After the fix the scheduler retries automatically: there is no need to recreate the pod.
