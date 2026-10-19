---
title: Node
summary: A cluster machine that runs pods through the kubelet and the container runtime.
category: concepts
order: 20
keywords: node, kubelet, conditions, ready, cordon, taint, capacity, allocatable
related: cluster, pod, scheduling, node-notready, proc-verificare-nodo, proc-manutenzione-nodo
---

## In simple terms

A node is a machine (physical or virtual) that is part of the cluster and runs pods. If pods are the tenants, nodes are the apartments: they have a certain amount of CPU, memory and disk, and Kubernetes fills them while respecting those limits.

A healthy node is **Ready**: it talks regularly with the control plane and can accept new pods. A **NotReady** node is a warning sign: its pods may not be working and, after a while, they will be moved elsewhere.

## Technical details

Each node runs `kubelet` (the agent that starts containers and reports status), the container runtime (containerd or CRI-O), `kube-proxy` and the CNI network plugin.

A node's `status` contains:

- **Conditions**: `Ready` (True/False/Unknown), `MemoryPressure`, `DiskPressure`, `PIDPressure`, `NetworkUnavailable`. `Ready=Unknown` means the kubelet has not sent a heartbeat for longer than `node-monitor-grace-period` (40 seconds by default).
- **Capacity** and **Allocatable**: total resources and those actually available to pods (capacity minus system reservations). The scheduler works on Allocatable and on the sum of [requests](guide:resource-request), not on actual usage.
- **nodeInfo**: kubelet version, operating system, runtime.

When a node becomes NotReady/Unknown, the controller adds the taints `node.kubernetes.io/not-ready` or `node.kubernetes.io/unreachable` with effect `NoExecute`; pods tolerate them for 300 seconds by default, then they are evicted and recreated elsewhere (if managed by a controller).

**Cordon** sets `spec.unschedulable: true`: no new pods, existing ones stay. **Drain** cordons and then evicts pods through the Eviction API. See [Node maintenance](guide:proc-manutenzione-nodo).

## Example

```bash
# Shell alternative
kubectl get nodes -o wide
kubectl describe node worker-02
kubectl top node worker-02          # requires metrics-server
kubectl get pods -A -o wide --field-selector spec.nodeName=worker-02
```

Excerpt of a node's status:

```yaml
status:
  allocatable:
    cpu: "3800m"
    memory: 15Gi
    pods: "110"
  conditions:
    - type: Ready
      status: "True"
    - type: DiskPressure
      status: "False"
```

## What can go wrong

- **NotReady / Unknown**: kubelet stopped, network down, node powered off. See [Node NotReady](guide:node-notready).
- **DiskPressure**: disk almost full; the kubelet removes unused images and may evict pods.
- **MemoryPressure**: low memory; pods evicted, starting with BestEffort ones.
- **Node full of requests**: new pods stay [Pending](guide:pending) even if actual usage is low.
- **Node left cordoned** after maintenance: capacity lost without anyone noticing.

## How to verify

- [Cluster → Nodi](app:/cluster/nodes): status, roles, version, conditions, whether it is schedulable.
- Node detail: **Eventi**, **Metriche** (CPU/RAM from metrics-server) and **Diagnostica** tabs.
- [Monitoraggio → CPU](app:/monitoring/cpu) and [Memoria](app:/monitoring/memory) to compare nodes.
- Procedure: [Verifying a node](guide:proc-verificare-nodo).

## How to fix

- NotReady: follow [Node NotReady](guide:node-notready); on the host check `systemctl status kubelet` and `journalctl -u kubelet`.
- DiskPressure: free up space (logs, unused images with `crictl rmi --prune`), then check that the condition goes back to False.
- Insufficient capacity: add nodes or reduce oversized requests.
- Maintenance: use [Operazioni → Manutenzione](app:/operations/maintenance) for cordon, drain and uncordon; do not forget the final uncordon.
