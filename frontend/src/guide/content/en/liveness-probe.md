---
title: Liveness probe
summary: The check that restarts a stuck container.
category: reliability
order: 50
keywords: liveness, liveness probe, probe, restart, health check, startup probe
related: readiness-probe, crashloopbackoff, container, pod, troubleshooting
---

## In simple terms

The **liveness probe** periodically asks the container: "are you still alive?". If the answer is no several times in a row, Kubernetes **kills the container and restarts it**. It is used to recover automatically from situations where the process is still running but no longer working (for example a deadlock).

Use it carefully: a badly configured liveness probe keeps restarting a healthy application.

## Technical details

- It is configured per container in `livenessProbe`, with the same mechanisms as readiness: `httpGet`, `tcpSocket`, `exec`, `grpc`.
- Parameters: `initialDelaySeconds`, `periodSeconds` (default 10), `timeoutSeconds` (default 1), `failureThreshold` (default 3), `terminationGracePeriodSeconds` (optional, at probe level). `successThreshold` must be 1.
- After `failureThreshold` failures, the kubelet sends SIGTERM to the container, waits for the grace period and then sends SIGKILL. The restart follows the Pod `restartPolicy` and increases `restartCount`.
- Repeated restarts lead to [CrashLoopBackOff](guide:crashloopbackoff), with increasing delays up to 5 minutes.
- Difference from readiness: readiness **removes from traffic**, liveness **restarts**. They can use different endpoints.
- For slow startups use a **startupProbe**: until it succeeds, liveness is suspended, so the container is not killed while still starting.
- Liveness should not depend on external services (database, APIs): if the DB goes down, restarting the application does not help and can make things worse.

## Example

```yaml
containers:
  - name: api
    image: registry.example.com/shop/api:2.3.1
    livenessProbe:
      httpGet:
        path: /healthz
        port: 8080
      periodSeconds: 15
      timeoutSeconds: 3
      failureThreshold: 4
    startupProbe:
      httpGet:
        path: /healthz
        port: 8080
      periodSeconds: 10
      failureThreshold: 18
```

With these values the container has up to 180 seconds to start; after that it is restarted if `/healthz` fails for about one minute.

## What can go wrong

- **Continuous restarts** of a healthy application: `timeoutSeconds` too low, no startupProbe, wrong path.
- **Restarts under load**: the application answers slowly when busy, the probe times out and the restart further reduces capacity.
- **Liveness depending on the database**: a DB problem restarts all replicas.
- **Probe identical to readiness** with aggressive thresholds: the Pod gets killed instead of just being removed from traffic.
- **No liveness** on an application that can hang: the Pod stays Running but does not answer.

## How to verify

- On the [Pod](app:/k8s/pods) page check the restarts column; the **Eventi** tab shows `Liveness probe failed` and `Container ... failed liveness probe, will be restarted`.
- In the **Log** tab pick the container and also look at the previous container's logs to understand what happened before the restart.
- The [Centro Operativo](app:/operations-center) flags Pods in CrashLoopBackOff.

```bash
kubectl -n shop describe pod api-5f6d7c9b8-q8w2n
kubectl -n shop logs api-5f6d7c9b8-q8w2n -c api --previous
```

## How to fix

1. Check path, port and response time of the liveness endpoint.
2. Add a `startupProbe` if the container is killed during startup.
3. Increase `timeoutSeconds` and `failureThreshold` to tolerate load spikes.
4. Make the liveness endpoint independent from external dependencies: it should only verify that the process can answer.
5. Apply the changes from the **YAML** tab (dry-run validation, diff, apply).
