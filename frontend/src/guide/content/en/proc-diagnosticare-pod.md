---
title: Diagnose a Pod
summary: Step-by-step procedure to understand why a Pod does not start, keeps restarting or does not respond.
category: procedures
order: 80
keywords: diagnosis, pod, events, logs, describe, crashloopbackoff, pending, troubleshooting
related: troubleshooting, pod, crashloopbackoff, imagepullbackoff, oomkilled, pending, proc-visualizzare-log
---

## When you need it

Use this procedure when a Pod is not in the expected state: it stays `Pending`, goes into `CrashLoopBackOff`, shows `ImagePullBackOff` or `ErrImagePull`, was terminated with `OOMKilled`, or is `Running` but the application does not respond. The problem usually appears first in the [Operations Center](app:/operations-center) or in the notification bell.

## Prerequisites

- A user with the **Operator** or **Administrator** role (Viewer can see status and events, but logs require at least Operator).
- Scarlet in LIVE mode and connected to the cluster (green "LIVE" badge at the top).
- The namespace of the application.

## Procedure

1. **Start from the detected problem.** Open the [Operations Center](app:/operations-center) and find the entry for the Pod. Read severity, risk and suggested actions: they often already point to the likely cause.
2. **Open the Pod detail.** Go to [Applications → Pod](app:/k8s/pods), filter by namespace and click the Pod. In the **Overview** (Panoramica) tab note the phase (`Pending`, `Running`, `Failed`...), restart count, assigned node and the state of each container.
3. **Read the events.** Open the **Events** tab. `Warning` events are the most useful: `FailedScheduling` (no suitable node), `Failed` with `ErrImagePull` (image or credentials), `BackOff` (container restarting), `Unhealthy` (failing probes), `FailedMount` (volume cannot be mounted).
4. **Read the logs.** Open the **Log** tab, choose the container and show the last 200-500 lines. If the container restarted, the useful logs are often those of the previous instance: look at the error printed right before the exit. See [View logs](guide:proc-visualizzare-log).
5. **Use the Diagnostics tab.** It summarizes the Pod conditions, the last terminated state (`lastState.terminated.reason` and `exitCode`) and the automatic checks. An `exitCode` 137 with reason `OOMKilled` means insufficient memory; an `exitCode` 1 usually means an application error.
6. **Check the relations.** In the **Relations** tab check which Deployment/StatefulSet owns the Pod, which Services select it, and which ConfigMaps, Secrets and PVCs it uses. A missing ConfigMap or Secret causes `CreateContainerConfigError`; a `Pending` PVC keeps the Pod `Pending`.
7. **Check the metrics.** In the **Metrics** tab compare CPU and memory with requests and limits (requires metrics-server; otherwise you will see "Metriche avanzate non configurate").
8. **Review the YAML.** In the **YAML** tab check image, tag, variables, probes and resources. Always fix the controller (Deployment, StatefulSet...), not the single Pod: the Pod would be recreated with the old configuration.
9. **Decide and act.** Depending on the cause: fix the image, raise the memory limit, create the missing Secret, perform a [rollback](guide:proc-rollback) or a restart from [Operations → Restart](app:/operations/restart).

Shell equivalents (for an administrator):

```bash
kubectl -n shop get pod web-7c9f8d6b5-x2kqp -o wide
kubectl -n shop describe pod web-7c9f8d6b5-x2kqp
kubectl -n shop logs web-7c9f8d6b5-x2kqp -c web --tail=200
kubectl -n shop logs web-7c9f8d6b5-x2kqp -c web --previous
kubectl -n shop get events --field-selector involvedObject.name=web-7c9f8d6b5-x2kqp
```

## Verification

- The Pod is in the `Running` phase and all containers are `Ready`.
- The restart counter no longer increases for at least a few minutes.
- The problem disappears from the Operations Center (or you can mark it as handled in the Notification Center).
- The related Service has active endpoints again in [Networking → Endpoints](app:/k8s/endpoints).

## If something goes wrong

- **You cannot see logs**: the container may never have started (image not pulled, missing configuration). In that case the cause is in the events, not in the logs.
- **The Pod disappears while you analyze it**: the controller replaced it. Look for the new Pod with the same name prefix.
- **The YAML change has no effect**: you probably edited the Pod rather than the controller. Apply the fix to the Deployment.
- **Several Pods have the same problem on a single node**: the node is probably at fault. Follow [Verify a node](guide:proc-verificare-nodo).
- For specific errors see [CrashLoopBackOff](guide:crashloopbackoff), [ImagePullBackOff](guide:imagepullbackoff), [OOMKilled](guide:oomkilled) and [Pending](guide:pending).
