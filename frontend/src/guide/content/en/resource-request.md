---
title: Resource request
summary: The minimum resources (CPU and RAM) a container declares it needs, used for scheduling.
category: reliability
order: 60
keywords: requests, resource request, cpu, memory, ram, millicore, scheduling, qos
related: resource-limit, scheduling, pending, node, oomkilled, monitoring
---

## In simple terms

A **request** is a reservation: the container declares "to work I need at least half a CPU and 256 MiB of RAM". Kubernetes uses this to choose a node with enough free **reservable** room, and guarantees that share to the container.

If no node has enough room for the reservation, the Pod does not start and stays [Pending](guide:pending).

## Technical details

- It is set in each container's `resources.requests`. Units:
  - CPU in cores or millicores: `500m` = half a core, `2` = two cores.
  - Memory in bytes with binary suffixes: `256Mi`, `1Gi` (careful: `M` and `Mi` are different).
- The **scheduler** sums the containers' requests (plus any overhead) and compares the total with the node's **allocatable** minus the requests of Pods already there. What counts is the reservation, **not** actual usage.
- At runtime the CPU request becomes a weight (`cpu.weight` on cgroup v2): under contention, each container gets CPU in proportion to its request.
- The memory request does not limit anything by itself, but it influences eviction order when the node is under memory pressure: Pods using more than their request are evicted first.
- If you set only the limit, the request is set equal to the limit.
- **QoS classes**: `Guaranteed` (request = limit for CPU and memory in all containers), `Burstable` (at least one request or limit), `BestEffort` (none). BestEffort Pods are evicted first.
- A **LimitRange** in the namespace can set default values; a **ResourceQuota** can cap the sum of requests.
- The HPA computes utilization as a percentage of the request: without requests, CPU autoscaling does not work.

## Example

```yaml
containers:
  - name: api
    image: registry.example.com/shop/api:2.3.1
    resources:
      requests:
        cpu: 250m
        memory: 256Mi
      limits:
        memory: 512Mi
```

In the [Deploy](app:/operations/deploy) wizard the **CPU** and **RAM** steps set these values.

Shell alternative to see how much is reserved on a node:

```bash
kubectl describe node worker-01 | grep -A 8 "Allocated resources"
kubectl top pod -n shop
```

## What can go wrong

- **Requests too high**: Pods `Pending` with event `0/3 nodes are available: 3 Insufficient cpu`, a cluster that looks "full" even with real CPU available.
- **Requests too low or missing**: too many Pods on the same node, CPU contention, slowness, evictions under memory pressure.
- **Namespace quota exceeded**: Pod creation is rejected (`exceeded quota`).
- **Wrong units**: `cpu: 500` means 500 cores, not 500 millicores.

## How to verify

- In [Monitoraggio → CPU](app:/monitoring/cpu) and [Memoria](app:/monitoring/memory) compare real usage with requests (requires metrics-server; without it the app shows "Metriche avanzate non configurate").
- On the [Nodi](app:/cluster/nodes) page check capacity, allocatable and reserved resources.
- The **Eventi** tab of a Pending Pod reports `FailedScheduling` with the reason.

## How to fix

1. Measure real usage for a few days and set the request close to typical usage.
2. If Pods stay Pending, lower the requests, free resources or add nodes.
3. For critical services set the memory request equal to the limit to get a more stable QoS.
4. Apply the changes from the workload **YAML** tab: changing resources triggers a [rolling update](guide:rolling-update).
