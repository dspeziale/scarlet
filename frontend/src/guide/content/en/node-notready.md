---
title: Node NotReady
summary: The node is not communicating correctly with the control plane and cannot reliably run new pods.
category: troubleshooting
order: 60
keywords: notready, node, kubelet, node conditions, memorypressure, diskpressure, pidpressure, network unavailable
related: node, proc-verificare-nodo, proc-manutenzione-nodo, alta-disponibilita, troubleshooting, pod-failed-unknown
---

## In simple terms

Every node runs an agent, the **kubelet**, which periodically tells the control plane "I am alive and well". If these reports stop or report a problem, the node becomes **NotReady**. The scheduler stops placing new pods on it and, after a few minutes, Kubernetes moves the controller-managed pods elsewhere.

Typical causes: the node is powered off or unreachable on the network, the kubelet or container runtime stopped, the disk is full, memory is exhausted, or the network plugin (CNI) is not working.

## Technical details

- The kubelet renews a `Lease` object in the `kube-node-lease` namespace (every 10 seconds by default) and the node status. If the node controller receives no updates for `node-monitor-grace-period` (40-50 seconds depending on the version), the `Ready` condition becomes `Unknown`.
- Values of the `Ready` condition: `True` (healthy), `False` (the kubelet responds but reports a problem, for example the runtime is down), `Unknown` (no news from the kubelet).
- Other conditions: `MemoryPressure`, `DiskPressure`, `PIDPressure`, `NetworkUnavailable`. When they are `True`, the kubelet may evict pods.
- The node automatically gets the `node.kubernetes.io/not-ready` or `node.kubernetes.io/unreachable` taints with `NoExecute` effect. Pods have a default toleration of 300 seconds: after 5 minutes they are evicted and recreated by their controllers on other nodes.
- StatefulSet pods on an unreachable node are not replaced automatically until Kubernetes is sure the old pod is stopped: this prevents two instances with the same identity.
- Pods that were on the node may show `Unknown` or `Terminating` (see [Pod Failed and Unknown](guide:pod-failed-unknown)).

## Example

```bash
kubectl get nodes
# NAME       STATUS     ROLES           AGE   VERSION
# worker-2   NotReady   <none>          41d   v1.30.4

kubectl describe node worker-2 | sed -n '/Conditions/,/Addresses/p'

# On the node (admin alternative)
sudo systemctl status kubelet
sudo journalctl -u kubelet --since "15 min ago"
sudo systemctl status crio    # or containerd
df -h /var
```

## What can go wrong

- `/var` full (logs, images): `DiskPressure` and a kubelet unable to work.
- The kubelet stops after an operating system update or because of an expired client certificate.
- Swap enabled after a reboot, if the kubelet is configured to refuse it.
- Network or firewall problems between the node and the API server (port 6443).
- System clock out of sync: TLS certificate errors.
- Rebooting the node without draining it: pods are interrupted abruptly.

## How to verify

1. The [Operations Center](app:/operations-center) reports NotReady nodes as a critical problem.
2. Open the node in [Cluster → Nodi](app:/cluster/nodes): **Panoramica** shows conditions, last heartbeat and taints.
3. In the node **Eventi** look for `NodeNotReady`, `KubeletNotReady`, `EvictionThresholdMet`.
4. In [Monitoraggio → Alta affidabilità](app:/monitoring/ha) check which workloads lost replicas.
5. Follow the [Verify a node](guide:proc-verificare-nodo) procedure.

## How to fix

1. Assess the impact: which applications had pods on the node and whether they still have healthy replicas elsewhere.
2. If the node is reachable, the system administrator checks kubelet, runtime, disk and network with the commands in the example.
3. If a long intervention is needed, **cordon** and, if the node responds, **drain** from [Operazioni → Manutenzione](app:/operations/maintenance) (see [Node maintenance](guide:proc-manutenzione-nodo)).
4. After recovery, check that the node returns to `Ready` and run **uncordon**.
5. If the node is permanently lost, the administrator removes it from the cluster (`kubectl delete node`) only after making sure pods with local storage have been handled.
