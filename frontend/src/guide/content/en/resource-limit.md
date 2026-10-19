---
title: Resource limit
summary: The maximum CPU and RAM a container is allowed to use.
category: reliability
order: 70
keywords: limits, resource limit, cpu, memory, ram, throttling, oomkilled, cgroup
related: resource-request, oomkilled, monitoring, container, node
---

## In simple terms

A **limit** is the ceiling: the container cannot use more than that amount of CPU or memory. It prevents a faulty application (for example one with a memory leak) from consuming the whole node and harming the others.

Exceeding it has different consequences:
- **CPU above the limit**: the container is **slowed down** (throttling), but keeps running.
- **Memory above the limit**: the container is **killed** by the kernel ([OOMKilled](guide:oomkilled)) and restarted.

## Technical details

- It is set in `resources.limits`, with the same units as [requests](guide:resource-request): `cpu: 1` or `500m`, `memory: 512Mi`.
- The kubelet translates limits into the container's cgroup settings (cgroup v2 on Oracle Linux 9): `cpu.max` for CPU and `memory.max` for memory.
- **CPU**: the quota is computed over 100 ms periods. A container with `limits.cpu: 500m` can use 50 ms of CPU every 100 ms; once used up, it waits for the next period. This causes latency even when the node has free CPU. Many organizations prefer to set only the CPU request and no CPU limit.
- **Memory**: if the container exceeds `memory.max`, the OOM killer terminates a process in the container; the container shows `Terminated` with reason `OOMKilled` and exit code 137.
- **Eviction** is different: when the whole node is under memory pressure, the kubelet evicts entire Pods (phase `Failed`, reason `Evicted`) even if they respect their own limits.
- The sum of limits of the Pods on a node can exceed node capacity (*overcommit*): it is allowed, but increases the risk of memory pressure.
- For Java, Node.js and similar applications, the runtime memory (heap) must be configured consistently with the limit, leaving room for stacks and native memory.

## Example

```yaml
containers:
  - name: worker
    image: registry.example.com/shop/worker:3.0.4
    env:
      - name: JAVA_TOOL_OPTIONS
        value: "-XX:MaxRAMPercentage=75"
    resources:
      requests:
        cpu: 500m
        memory: 768Mi
      limits:
        cpu: "2"
        memory: 1Gi
```

Shell alternative to check for an OOMKilled:

```bash
kubectl -n shop get pod worker-6b8f9d7c4-l9zt2 \
  -o jsonpath='{.status.containerStatuses[0].lastState.terminated.reason}'
```

## What can go wrong

- **Memory limit too low**: repeated OOMKilled, ending in [CrashLoopBackOff](guide:crashloopbackoff).
- **CPU limit too low**: high response times, probe timeouts, restarts caused by the [liveness probe](guide:liveness-probe).
- **No memory limit**: a leak can saturate the node and cause other Pods to be evicted.
- **Runtime heap larger than the limit**: the application is killed before the garbage collector kicks in.
- A namespace **LimitRange** that imposes unsuitable default limits.

## How to verify

- In [Monitoraggio → Memoria](app:/monitoring/memory) and [CPU](app:/monitoring/cpu) compare usage with limits (data from metrics-server; history requires Prometheus).
- In the Pod detail the **Diagnostica** tab flags OOMKilled and restarts; the **Metriche** tab shows current usage.
- The [Centro Operativo](app:/operations-center) lists OOMKilled containers.

## How to fix

1. If the container is OOMKilled, increase `limits.memory` (or reduce the configured heap) after checking it is not a leak.
2. If there is CPU throttling, increase `limits.cpu` or remove it while keeping a proper request.
3. Keep a reasonable ratio between memory request and limit (equal for critical services).
4. Edit the manifest in the **YAML** tab, validate, review the diff and apply.
