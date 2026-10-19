---
title: DaemonSet
summary: Runs one copy of a Pod on every node (or on a group of nodes), typically for system agents.
category: workloads
order: 40
keywords: daemonset, agent, node, log collector, cni, taint, toleration
related: node, scheduling, pod, proc-manutenzione-nodo, monitoring
---

## In simple terms

A **DaemonSet** makes sure that **every node** in the cluster runs a copy of a given Pod. When you add a node, the Pod automatically appears there too; when you remove the node, the Pod goes away.

It is used for "system services" that must run on every machine: log collection (Fluent Bit), node monitoring (node-exporter), cluster networking (Calico, Cilium, Flannel), storage drivers (CSI node plugin), kube-proxy.

## Technical details

- It has no `replicas`: the number of Pods depends on eligible nodes. `status.desiredNumberScheduled`, `currentNumberScheduled`, `numberReady` and `numberUnavailable` describe the state.
- Eligible nodes are restricted with `spec.template.spec.nodeSelector` or `affinity`.
- Nodes with **taints** (e.g. control-plane nodes with `node-role.kubernetes.io/control-plane:NoSchedule`) are excluded unless the Pod has a matching `toleration`. The controller automatically adds some tolerations (for example for `node.kubernetes.io/not-ready` and `unreachable` with NoExecute effect, and `unschedulable`).
- DaemonSet Pods are scheduled by the default scheduler through node affinity to the specific node.
- `updateStrategy`: `RollingUpdate` (default, `maxUnavailable: 1`) or `OnDelete`.
- During a node **drain** DaemonSet Pods are **skipped**: they would be recreated immediately on the same node anyway. PKM's drain in [Operazioni → Manutenzione](app:/operations/maintenance) does exactly this.

In PKM: [Applicazioni → DaemonSets](app:/k8s/daemonsets).

## Example

```yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: node-exporter
  namespace: monitoring
spec:
  selector:
    matchLabels: { app: node-exporter }
  template:
    metadata:
      labels: { app: node-exporter }
    spec:
      tolerations:
        - key: node-role.kubernetes.io/control-plane
          operator: Exists
          effect: NoSchedule
      containers:
        - name: node-exporter
          image: quay.io/prometheus/node-exporter:v1.8.2
          ports: [{ containerPort: 9100, hostPort: 9100 }]
          resources:
            requests: { cpu: 50m, memory: 32Mi }
            limits: { memory: 64Mi }
```

## What can go wrong

- **Desired ≠ Ready**: on some nodes the Pod does not start (image cannot be pulled, `hostPort` already in use, insufficient permissions).
- **Node unexpectedly excluded**: a toleration for a taint is missing or the nodeSelector does not match the node labels.
- **Node resources exhausted**: an agent without a memory limit can push the node into pressure and cause evictions of other Pods.
- **Broken network or storage DaemonSet**: all Pods on that node may have network or volume mount problems; often the node becomes [NotReady](guide:node-notready).

## How to verify

In PKM open the DaemonSet and compare scheduled/ready; the Relazioni tab shows which node each Pod runs on.

```bash
kubectl -n monitoring get daemonset node-exporter
kubectl -n monitoring get pods -l app=node-exporter -o wide
kubectl describe node <node> | grep -i taints
```

## How to fix

1. Identify the node where the Pod is missing or failing and read the Pod's events.
2. If the node is excluded, add the toleration or fix the nodeSelector in the YAML tab (validate with dry-run before applying).
3. For `hostPort` conflicts, find the process or Pod using the port on the node.
4. Always set requests and limits on agents: see [Resource limit](guide:resource-limit).
5. If an update breaks the agents, perform a [rollback](guide:rollback) (`kubectl rollout undo daemonset/node-exporter`).
