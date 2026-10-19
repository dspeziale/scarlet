---
title: CrashLoopBackOff
summary: The container starts, exits immediately and Kubernetes restarts it with increasingly longer waits.
category: troubleshooting
order: 20
keywords: crashloopbackoff, crash, restarts, restart, back-off, exit code, previous logs
related: troubleshooting, oomkilled, liveness-probe, rollback, proc-diagnosticare-pod, proc-visualizzare-log
---

## In simple terms

**CrashLoopBackOff** is not an error in itself: it is the waiting state Kubernetes puts a container in when it keeps exiting. The container starts, the main process exits (because of an error or even normally), the kubelet restarts it, it exits again… and between attempts it waits longer and longer. The real cause is always **inside the container**: an application error, a wrong configuration, an unreachable dependency, insufficient memory or an overly aggressive liveness probe.

## Technical details

- With `restartPolicy: Always` (the default for Deployment, StatefulSet, DaemonSet) the kubelet restarts the container every time it exits. The delay grows exponentially: 10s, 20s, 40s… up to a maximum of 5 minutes. The counter resets after 10 minutes of trouble-free execution.
- While waiting, the container is in `state.waiting.reason: CrashLoopBackOff`; the last exit is in `lastState.terminated` with `exitCode`, `reason` and timestamps.
- Useful exit codes:

| Exit code | Typical meaning |
|---|---|
| 0 | the process exited normally (for example an image with no foreground process) |
| 1 | generic application error |
| 126 / 127 | command not executable / not found (wrong `command` or `args`) |
| 137 | killed with SIGKILL: often [OOMKilled](guide:oomkilled) or a failed liveness probe |
| 139 | segmentation fault |
| 143 | SIGTERM, requested termination |

- If the liveness probe fails, events show `Liveness probe failed` and `Container ... failed liveness probe, will be restarted`.

## Example

```bash
kubectl get pod api-6c8d9f7b4-q7wzn -n shop
# NAME                    READY   STATUS             RESTARTS      AGE
# api-6c8d9f7b4-q7wzn     0/1     CrashLoopBackOff   6 (2m ago)    9m

kubectl describe pod api-6c8d9f7b4-q7wzn -n shop | grep -A5 "Last State"
kubectl logs api-6c8d9f7b4-q7wzn -n shop --previous --tail=100
```

A typical log line: `Error: connect ECONNREFUSED 10.96.12.4:5432` means the database is not reachable.

## What can go wrong

- The logs of the current instance are empty because the container is waiting: you must read the **previous** ones.
- The crash is caused by an environment variable or a ConfigMap/Secret file changed recently.
- A dependency (database, external API) is not ready and the application exits instead of retrying.
- The liveness probe starts before the application has finished starting (no `startupProbe`, or `initialDelaySeconds` too low).
- A new release introduced a bug: all new pods crash while the old ones work.

## How to verify

1. In the [Operations Center](app:/operations-center) the problem appears as CrashLoopBackOff with the affected pod.
2. Open the pod from [Applicazioni → Pod](app:/k8s/pods): in **Panoramica** check restarts, exit code and the reason of the last termination.
3. In the **Log** tab select the container and the previous-instance option; look at the last lines before the exit.
4. In the **Eventi** tab look for `BackOff`, `Liveness probe failed`, `OOMKilling`.
5. In **Metriche** check whether memory grows up to the limit before each crash.

## How to fix

1. If the problem appeared after a release, perform a [rollback](guide:proc-rollback) from the [Rollout](app:/operations/rollout) page: it is the fastest way to restore the service.
2. Application or configuration error: fix the ConfigMap, Secret or variables, then restart from [Operazioni → Restart](app:/operations/restart).
3. Exit code 137 with `OOMKilled`: follow [OOMKilled](guide:oomkilled).
4. Liveness probe: increase `initialDelaySeconds`, `timeoutSeconds` or `failureThreshold`, or add a `startupProbe` (see [Liveness probe](guide:liveness-probe)).
5. Exit code 0 or 127: check `command` and `args` in the **YAML** tab, validate with the dry-run and apply.

Restarting the pod without fixing the cause is pointless: the counter resets, but the crash comes back.
