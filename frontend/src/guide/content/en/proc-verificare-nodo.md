---
title: Verify a node
summary: How to check the health of a node and understand whether it can host workloads.
category: procedures
order: 90
keywords: node, notready, conditions, pressure, kubelet, capacity, verify
related: node, node-notready, proc-manutenzione-nodo, monitoring, scheduling, pending
---

## When you need it

- The [Operations Center](app:/operations-center) reports a `NotReady` node.
- Several Pods on the same node fail, get evicted or stay `Pending`.
- Before and after maintenance, to confirm the node is healthy.
- During a periodic check of cluster capacity.

## Prerequisites

- Any role can view nodes; cordon, drain and uncordon require at least **Operator**.
- Real-time CPU and memory require metrics-server installed in the cluster.
- Actions on the node operating system (restarting kubelet, checking disks) require SSH access to the node: Scarlet does not run commands on nodes.

## Procedure

1. **Open the node list.** Go to [Cluster → Nodes](app:/cluster/nodes). For each node check the status (`Ready`/`NotReady`), roles, kubelet version, whether it is schedulable (a cordoned node shows `SchedulingDisabled`) and age.
2. **Open the node detail.** In the **Overview** tab check the **conditions**:
   - `Ready=True`: the kubelet responds and is healthy.
   - `MemoryPressure`, `DiskPressure`, `PIDPressure` must be `False`. If one is `True`, the kubelet starts evicting Pods.
   - `NetworkUnavailable` must be `False`.
   - `Ready=Unknown` means the control plane no longer hears from the kubelet (by default after about 40 seconds).
3. **Check capacity and allocation.** Compare `capacity` and `allocatable` with the sum of the requests of the Pods on it. A node whose requests are at 100% does not accept new Pods even if real usage is low.
4. **Check the metrics.** In the **Metrics** tab or in [Monitoring → CPU](app:/monitoring/cpu) and [Memory](app:/monitoring/memory) check actual usage. Usage constantly above 85-90% is a risk signal.
5. **Read the node events.** In the **Events** tab look for `NodeNotReady`, `NodeHasDiskPressure`, `EvictionThresholdMet`, `Rebooted`.
6. **Look at the hosted Pods.** In the **Relations** tab check which Pods run on the node and whether any is in an abnormal state.
7. **Check taints.** In the node YAML check `spec.taints`: a `NoSchedule` taint prevents scheduling of Pods without a matching toleration. The `node.kubernetes.io/unreachable` taint is added automatically to unreachable nodes.

Shell equivalents:

```bash
kubectl get nodes -o wide
kubectl describe node worker-02
kubectl top node worker-02
kubectl get pods -A --field-selector spec.nodeName=worker-02
# on the node, via SSH
systemctl status kubelet
journalctl -u kubelet --since "30 min ago"
df -h /var/lib
```

## Verification

- The node is `Ready` and all pressure conditions are `False`.
- The node is not `SchedulingDisabled`, unless intentionally for maintenance.
- CPU and memory usage leave enough headroom.
- No recent `Warning` events on the node.
- The [Health](app:/monitoring/health) page shows Kubernetes as Healthy.

## If something goes wrong

- **Node `NotReady`**: check via SSH that the node is up and that `kubelet` and the container runtime are running; check network and certificates. Details in [Node NotReady](guide:node-notready).
- **`DiskPressure`**: free space on the node (unused images, logs); the kubelet also tries image garbage collection on its own.
- **`MemoryPressure`**: some Pods use more memory than they request. Review [requests](guide:resource-request) and [limits](guide:resource-limit).
- **The node must be repaired**: put it into maintenance with cordon and drain, see [Node maintenance](guide:proc-manutenzione-nodo).
- **Metrics unavailable**: "Metriche avanzate non configurate" is shown. Install metrics-server or configure Prometheus in Settings.
