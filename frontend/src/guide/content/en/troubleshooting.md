---
title: Troubleshooting method
summary: A repeatable method to understand and fix pod, node and application problems without guesswork.
category: troubleshooting
order: 10
keywords: troubleshooting, diagnosis, problems, errors, operations center, events, logs, method
related: crashloopbackoff, imagepullbackoff, oomkilled, pending, node-notready, proc-diagnosticare-pod, proc-gestione-incidenti
---

## In simple terms

When something breaks, the temptation is to restart everything right away. The problem often disappears for a few minutes and then comes back, and in the meantime the evidence is gone. Effective troubleshooting follows a method: **Understand → Diagnose → Decide → Act → Verify**. First you collect facts (status, events, logs), then you form a hypothesis, choose the lowest-risk action, perform it and check that the problem is really solved.

PKM is built around this method: the [Operations Center](app:/operations-center) automatically detects the most common problems, every resource has a **Diagnostica** tab, and actions (restart, rollback, scale) are one click away, but only after you understand what is happening.

## Technical details

A Kubernetes problem almost always shows up at one of these levels:

| Level | Where to look | Typical signals |
|---|---|---|
| Pod / container | pod status, `status.containerStatuses` | CrashLoopBackOff, ImagePullBackOff, OOMKilled, CreateContainerConfigError |
| Scheduling | pod events (`FailedScheduling`) | Pending |
| Node | node conditions (`Ready`, `MemoryPressure`, `DiskPressure`, `PIDPressure`) | NotReady, evictions |
| Network | Service, Endpoints, Ingress, DNS | empty Endpoints, 502/503 from the Ingress |
| Storage | PVC, PV, StorageClass | Pending PVC, failed mounts (`FailedMount`) |
| Configuration | ConfigMap, Secret, variables | missing keys, wrong values |

There are three main sources of information:

- **Status**: the pod phase (`Pending`, `Running`, `Succeeded`, `Failed`, `Unknown`) and, more importantly, the state of each container (`waiting.reason`, `terminated.reason`, `exitCode`, `restartCount`).
- **Events**: short messages produced by controllers and the kubelet. By default they last about one hour, so read them early.
- **Logs**: the process output. For a restarting container, the useful logs are often those of the **previous** instance (`--previous`).

The Operations Center assigns a severity (CRITICAL, ERROR, WARNING, INFO), shows the affected resource, the risk and suggested actions. CPU and memory metrics require metrics-server: if it is not installed, PKM shows "Metriche avanzate non configurate" and never invents values.

## Example

Shell equivalent of the path PKM follows in the Diagnostica tab:

```bash
kubectl get pods -n shop -o wide
kubectl describe pod web-7d9f8c6b5-x2k4q -n shop      # status and events
kubectl logs web-7d9f8c6b5-x2k4q -n shop --previous   # logs of the previous instance
kubectl get events -n shop --sort-by=.lastTimestamp
kubectl top pod -n shop                                # requires metrics-server
```

## What can go wrong

- **Acting before understanding**: a restart wipes the state and logs of the failing container.
- **Looking only at logs**: if the container never starts (image not found, missing Secret), logs are empty. The cause is in the events.
- **Stopping at the symptom**: a 502 from the Ingress may be caused by a wrong readiness probe, not by the Ingress.
- **Expired events**: after about an hour events disappear; write down what you see immediately.
- **Changing several things at once**: if the problem goes away you will not know which change fixed it.

## How to verify

1. Open the [Operations Center](app:/operations-center) and sort by severity.
2. Open the affected resource and check, in order: **Panoramica**, **Eventi**, **Log**, **Metriche**, **Diagnostica**.
3. Check cluster events in [Cluster → Eventi](app:/cluster/events) to see whether the problem is isolated or widespread.
4. Check node status in [Cluster → Nodi](app:/cluster/nodes).

## How to fix

1. **Understand**: describe the symptom in one sentence ("3 of 3 pods of deployment `web` in CrashLoopBackOff since 10:20").
2. **Diagnose**: identify the level (pod, node, network, storage, config) and read the specific article, for example [CrashLoopBackOff](guide:crashloopbackoff) or [Pending](guide:pending).
3. **Decide**: choose the least invasive action. If the problem started with a release, a [rollback](guide:proc-rollback) is often the safest choice.
4. **Act**: make one change at a time from the Operazioni pages. Every action is recorded in the Audit Log.
5. **Verify**: check that pods are `Running` and `Ready`, that the restart count is stable and that the problem has disappeared from the Operations Center. Mark the problem as handled in the Notification Center.

For incidents involving several services, follow the [Incident management](guide:proc-gestione-incidenti) procedure.
