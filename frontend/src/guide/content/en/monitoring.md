---
title: Monitoring
summary: Where metrics, events, logs and health status come from in Scarlet, and how to read them without being misled.
category: concepts
order: 70
keywords: monitoring, metrics, metrics-server, prometheus, health, events, logs, cpu, memory
related: resource-request, resource-limit, node, proc-visualizzare-log, troubleshooting, oomkilled
---

## In simple terms

Monitoring means knowing at any moment whether applications and the cluster are healthy, and noticing problems before users do. In Scarlet you have four sources of information:

- **Metrics**: how much CPU, memory, disk and network pods and nodes use.
- **Events**: what just happened in the cluster (pods created, failed pulls, impossible scheduling...).
- **Logs**: what applications write.
- **Health**: whether Scarlet itself and the systems it connects to are working.

The [Operations Center](app:/operations-center) combines these sources and shows you problems that are already interpreted.

## Technical details

**CPU/RAM metrics** for pods and nodes come from **metrics-server** (the `metrics.k8s.io` API). They are point-in-time values, sampled roughly every 15 seconds, with no history. **History and network metrics** come from **Prometheus**, if configured in [Impostazioni → Kubernetes](app:/settings/kubernetes). If neither is available, Scarlet shows "Metriche avanzate non configurate" (advanced metrics not configured): it **never estimates or invents values**.

How to read the numbers:

- CPU in **millicores** (`250m` = a quarter of a core). Exceeding the CPU limit does not kill the container: it **slows it down** (throttling).
- Memory in bytes (`Mi`, `Gi`). The reported value is the **working set**, which the kernel uses to decide on OOM. Exceeding the memory limit causes [OOMKilled](guide:oomkilled).
- Always compare usage with [requests](guide:resource-request) and [limits](guide:resource-limit): a pod at 95% of its memory limit is at risk even if it "works".

Kubernetes **events**: `Event` objects with type `Normal` or `Warning`, a `reason` and a message. They are kept for a limited time (1 hour by default): for past incidents you cannot rely on events alone.

**Logs**: read through the kubelet API; see [Viewing logs](guide:proc-visualizzare-log). Limits: 5000 lines per request, streaming stops after 30 minutes or 20000 lines.

**Health**: the [Health](app:/monitoring/health) page checks backend, database, Kubernetes, Podman, free space in the data directory, configuration, metrics-server and Prometheus, with status Healthy, Degraded or Unhealthy.

## Example

```bash
# Shell alternative
kubectl top nodes
kubectl top pods -n orders --containers --sort-by=memory
kubectl get events -A --field-selector type=Warning --sort-by=.lastTimestamp
kubectl get apiservice v1beta1.metrics.k8s.io
```

Quick reading of a pod:

| Metric | Value | Request | Limit | Reading |
|---|---|---|---|---|
| CPU | 480m | 200m | 500m | close to the limit: likely throttling |
| Memory | 490Mi | 256Mi | 512Mi | 96% of the limit: OOMKilled risk |

## What can go wrong

- **metrics-server not installed or not working**: CPU/Memory pages show no data; Health flags metrics-server.
- **Prometheus not configured**: no history and no network metrics.
- **Expired events**: after an hour the cause of an overnight problem is no longer in the events.
- **Lost logs**: once the pod is recreated, the old pod's logs are gone (except the previous container within the same pod).
- Misreading: looking at the node average and ignoring the single pod close to its limit.

## How to verify

- [Monitoraggio → CPU](app:/monitoring/cpu), [Memoria](app:/monitoring/memory), [Storage](app:/monitoring/storage).
- [Monitoraggio → Health](app:/monitoring/health): metrics-server and Prometheus must be Healthy if you use them.
- [Monitoraggio → Eventi](app:/monitoring/events) and [Log](app:/monitoring/logs).

## How to fix

- Install or repair metrics-server (a cluster administrator task); check with `kubectl get apiservice v1beta1.metrics.k8s.io`.
- Configure the Prometheus URL in the settings to get history and network metrics.
- To avoid losing logs and events, use a centralized solution (e.g. the cluster's logging stack); Scarlet complements it, it does not replace it.
- When a pod is steadily close to its limits, review requests and limits instead of waiting for the incident.
