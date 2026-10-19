---
title: Checking cluster health
summary: A quick, repeatable cluster health check, to run at the start of a shift or after any intervention.
category: procedures
order: 40
keywords: check, health, cluster, nodes, events, operations center, verification
related: cluster, node, monitoring, proc-verificare-nodo, troubleshooting, node-notready
---

## When you need it

- At the start of a shift, as a routine check.
- After an intervention (upgrade, node maintenance, important deploy).
- When someone reports "the application is slow" or "not responding" and you want to understand whether the problem is the cluster or a single application.

## Prerequisites

- PKM connected to the cluster (**LIVE** badge visible). If you see the **DEMO** banner, you are looking at sample data.
- At least the **Viewer** role.

## Procedure

1. **Health of PKM and its integrations.** Open [Monitoraggio → Health](app:/monitoring/health). Backend, database, Kubernetes and Podman should be **Healthy**. If Kubernetes is Unhealthy, everything you see next may be incomplete: fix the connection first ([Connecting Kubernetes](guide:proc-collegare-kubernetes)).

2. **Already detected problems.** Open the [Centro Operativo](app:/operations-center). Sort by severity: **CRITICAL** and **ERROR** first, then WARNING. For each entry read the affected resource, the risk and the suggested actions.

3. **Nodes.** In [Cluster → Nodi](app:/cluster/nodes) all nodes must be **Ready**. Also check:
   - nodes marked **SchedulingDisabled** (a cordon forgotten after maintenance?);
   - pressure conditions: `MemoryPressure`, `DiskPressure`, `PIDPressure` must be `False`.

4. **Resource usage.** In [Monitoraggio → CPU](app:/monitoring/cpu) and [Memoria](app:/monitoring/memory) look for nodes steadily above 80-90%. If "Metriche avanzate non configurate" appears, metrics-server is not available: PKM never invents values. In [Storage](app:/monitoring/storage) check free space.

5. **Workloads.** In [Applicazioni → Deployments](app:/k8s/deployments) compare desired and ready replicas (e.g. `3/3`). A persistent `2/3` indicates a problem. Do the same for StatefulSets and DaemonSets.

6. **Recent events.** In [Cluster → Eventi](app:/cluster/events) filter by type **Warning** and look at the last 30-60 minutes. Repeated events (`BackOff`, `FailedScheduling`, `FailedMount`, `Unhealthy`) are valuable clues.

7. **Storage.** In [Persistent Volume Claims](app:/k8s/persistentvolumeclaims) no PVC should stay **Pending** for long.

8. **High availability.** In [Monitoraggio → Alta affidabilità](app:/monitoring/ha) check that critical applications have multiple replicas spread across different nodes.

Shell alternative, for an administrator:

```bash
kubectl get nodes -o wide
kubectl get pods -A --field-selector=status.phase!=Running,status.phase!=Succeeded
kubectl get events -A --field-selector type=Warning --sort-by=.lastTimestamp | tail -30
kubectl top nodes           # requires metrics-server
kubectl get pvc -A | grep -v Bound
```

## Verification

The cluster can be considered healthy when:

- Health is all **Healthy** (or Degraded only for optional components such as Prometheus);
- the Centro Operativo has no open CRITICAL or ERROR entries;
- all nodes are Ready and schedulable;
- Deployments have ready replicas equal to desired replicas;
- there are no repeated Warning events in the last minutes.

Record the outcome, especially for start-of-shift checks: it will help you understand **when** something changed.

## If something goes wrong

- **A node is NotReady**: follow [Node NotReady](guide:node-notready) and [Checking a node](guide:proc-verificare-nodo).
- **Pods in error**: use [Diagnosing a Pod](guide:proc-diagnosticare-pod).
- **Many problems at once**: there is probably a common cause (a node, the network, storage, an unreachable registry). Do not fix symptoms one by one: apply the [troubleshooting method](guide:troubleshooting) and, if users are affected, [incident management](guide:proc-gestione-incidenti).
