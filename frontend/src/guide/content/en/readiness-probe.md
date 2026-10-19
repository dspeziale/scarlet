---
title: Readiness probe
summary: The check that tells Kubernetes when a Pod is ready to receive traffic.
category: reliability
order: 40
keywords: readiness, readiness probe, probe, health check, ready, endpoints, startup probe
related: liveness-probe, service, rolling-update, networking, pod
---

## In simple terms

The **readiness probe** is a question Kubernetes periodically asks the container: "are you ready to serve requests?". As long as the answer is no, the Pod receives no traffic from the Service. The container is **not** restarted: it is simply kept out of rotation until it is ready again.

It is useful at startup (the application is still loading) and during temporary trouble (a dependency is not responding, the Pod is overloaded).

## Technical details

- It is configured per container in `readinessProbe`. Available mechanisms: `httpGet` (success with status 200-399), `tcpSocket` (port open), `exec` (command with exit code 0), `grpc`.
- Main parameters: `initialDelaySeconds`, `periodSeconds` (default 10), `timeoutSeconds` (default 1), `successThreshold` (default 1), `failureThreshold` (default 3).
- The result sets the `Ready` condition of the container and the Pod. A non-Ready Pod is moved among the **not ready** addresses of the EndpointSlice, so the Service does not forward traffic to it.
- A [rolling update](guide:rolling-update) uses readiness to decide when to proceed: without a probe a Pod is Ready as soon as the process starts.
- Without a `readinessProbe` the container is considered ready right after startup.
- The **startupProbe** is complementary: until it succeeds, liveness and readiness probes are not run. Use it for slow-starting applications.
- Good practice: a dedicated, lightweight endpoint (e.g. `/ready`) that checks only what is really needed to answer. Avoid failing readiness on dependencies shared by all replicas: they would all go out of service together.

## Example

```yaml
containers:
  - name: web
    image: registry.example.com/shop/web:1.5.0
    ports:
      - containerPort: 8080
    readinessProbe:
      httpGet:
        path: /ready
        port: 8080
      initialDelaySeconds: 5
      periodSeconds: 10
      timeoutSeconds: 2
      failureThreshold: 3
    startupProbe:
      httpGet:
        path: /ready
        port: 8080
      periodSeconds: 5
      failureThreshold: 30
```

The [Deploy](app:/operations/deploy) wizard lets you configure it in the **Health check** step.

## What can go wrong

- **Pod Running but 0/1 Ready**: the probe always fails (wrong path, wrong port, timeout too low).
- **Service without endpoints**: no Pod is ready, users get 503 errors from the Ingress.
- **Stuck rollout**: new Pods never become Ready.
- **Probe too heavy**: it queries the database on every check and adds load.
- **Cascading failure**: all replicas depend on the same external service and become not ready together.

## How to verify

- On the [Pod](app:/k8s/pods) page the Ready column shows ready containers; the **Eventi** tab reports `Readiness probe failed` messages with the reason (e.g. HTTP status or timeout).
- The Pod **Diagnostica** tab flags failing probes.
- In [Endpoints](app:/k8s/endpoints) check whether the Service has ready addresses.

```bash
kubectl -n shop describe pod web-7d9c8b6f5-x2k4q
kubectl -n shop get endpointslices -l kubernetes.io/service-name=web
kubectl -n shop exec web-7d9c8b6f5-x2k4q -- wget -qO- http://localhost:8080/ready
```

## How to fix

1. Check that the probe path and port match the application's real ones.
2. Increase `timeoutSeconds` or `initialDelaySeconds` if the application is slow; for very long startups use a `startupProbe`.
3. If the probe fails because of an external dependency, decide whether excluding the Pod is right or whether degrading functionality is enough.
4. Edit the manifest in the **YAML** tab, validate with the dry-run and apply: a rolling update will start.
