---
title: OOMKilled
summary: The container exceeded its memory limit and was terminated by the kernel.
category: troubleshooting
order: 40
keywords: oomkilled, out of memory, memory, limit, exit code 137, oom killer, memory pressure
related: resource-limit, resource-request, crashloopbackoff, monitoring, troubleshooting, node-notready
---

## In simple terms

Every container can have a **memory limit**. If the process tries to use more, the Linux kernel kills it immediately: this is the **OOM killer** (Out Of Memory). Kubernetes records the termination with reason **OOMKilled** and exit code **137**, then restarts the container. If it keeps happening, the pod ends up in [CrashLoopBackOff](guide:crashloopbackoff).

There are two typical causes: the limit is too low for the real load, or the application has a memory leak and grows until it is killed.

## Technical details

- `resources.limits.memory` becomes a limit on the container cgroup. Exceeding it causes an immediate SIGKILL, with no graceful shutdown.
- The state is visible in `status.containerStatuses[].lastState.terminated.reason: OOMKilled` with `exitCode: 137`.
- CPU behaves differently: exceeding the CPU limit only causes slowdown (throttling), never termination.
- There is also **node-level** OOM: if the node runs out of memory, the kubelet under `MemoryPressure` evicts pods starting with the lowest QoS class (`BestEffort`, then `Burstable` pods exceeding their requests, finally `Guaranteed`). In that case the pod is `Failed` with `reason: Evicted`.
- Runtimes such as the JVM or Node.js have configurable heaps: if the maximum heap is close to or above the container limit, OOM is guaranteed. With Java, for example, `-XX:MaxRAMPercentage=75` is recommended.

## Example

```bash
kubectl get pod report-7b5d4c9f8-h6t2r -n batch -o jsonpath='{.status.containerStatuses[0].lastState.terminated}'
# {"exitCode":137,"reason":"OOMKilled","startedAt":"...","finishedAt":"..."}

kubectl top pod report-7b5d4c9f8-h6t2r -n batch   # requires metrics-server
```

```yaml
resources:
  requests:
    memory: "512Mi"
    cpu: "250m"
  limits:
    memory: "1Gi"
```

## What can go wrong

- The limit is raised without raising the request: the pod is scheduled on nodes that do not really have that memory free and the node goes under pressure.
- The limit is raised indefinitely to hide a memory leak: the problem moves to the node.
- The limit is set in the wrong units (`1G` versus `1Gi`, or `512m`, which means 0.512 bytes).
- Memory spikes at startup (caches, data loading) exceed the limit even if steady-state usage is low.
- Without metrics-server the memory trend is not visible: PKM shows "Metriche avanzate non configurate".

## How to verify

1. In the [Operations Center](app:/operations-center) the problem appears as OOMKilled.
2. Open the pod: in **Panoramica** check the reason of the last termination and the restart count.
3. In **Metriche** compare memory usage with the limit; a sawtooth pattern hitting the limit indicates repeated OOMs.
4. In [Monitoraggio → Memoria](app:/monitoring/memory) check whether the node is under pressure.
5. In the node **Eventi** look for `SystemOOM` or `Evicted`.

## How to fix

1. If memory usage is stable but close to the limit: increase `limits.memory` (and `requests.memory` accordingly) from the Deployment **YAML** tab or with a new deploy, validating with the dry-run.
2. Configure the runtime according to the limit (JVM heap, Node.js `--max-old-space-size`).
3. If memory grows without stopping: it is a memory leak; as a temporary mitigation increase the [replicas](guide:replica) and report the problem to the developers.
4. If the problem is at node level: reduce the load, move pods or add capacity (see [Resource request](guide:resource-request)).
5. If it appeared after a release, consider a [rollback](guide:proc-rollback).
