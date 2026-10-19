---
title: Container
summary: An isolated process started from an image, run by Kubernetes inside a pod or directly by Podman.
category: concepts
order: 50
keywords: container, image, tag, digest, registry, entrypoint, exit code, podman
related: pod, cos-e-podman, imagepullbackoff, crashloopbackoff, oomkilled, resource-limit
---

## In simple terms

A container is a program running isolated from the rest of the system, with its own files, libraries and configuration, all taken from an **image**. The image is the "package" (for example `nginx:1.27`); the container is that package running.

In Scarlet containers show up in two places:

- inside Kubernetes **pods** (the pod's Panoramica tab, with the state of each container);
- in the **Container** section for Podman hosts ([Container](app:/podman/containers), [Immagini](app:/podman/images), [Registry](app:/podman/registries)), where an Operator can start, stop and restart containers.

## Technical details

**Image**: a set of layers in OCI format, identified by `registry/repository:tag` (e.g. `quay.io/acme/orders:2.4.1`) or, immutably, by a **digest** `@sha256:...`. The `latest` tag moves: avoid it in production, because two nodes may run different versions.

**imagePullPolicy** in Kubernetes: `IfNotPresent` (default with a specific tag), `Always` (default with `latest` or no tag), `Never`. Credentials for private registries are passed with `imagePullSecrets`.

**Container states in a pod** (`status.containerStatuses[].state`):

- `waiting` with a reason (`ContainerCreating`, `CrashLoopBackOff`, `ImagePullBackOff`, `CreateContainerConfigError`...);
- `running` with the start time;
- `terminated` with `exitCode` and `reason` (`Completed`, `Error`, `OOMKilled`).

`lastState` keeps the last termination: it is the first place to look after a restart. Useful exit codes: `0` normal exit, `1` generic application error, `137` killed with SIGKILL (often OOM or a failed liveness probe), `143` SIGTERM, `126/127` command not executable or not found.

**Isolation**: Linux namespaces (pid, net, mnt, user), cgroups for CPU and memory ([limits](guide:resource-limit)), SELinux on Oracle Linux. The container filesystem is ephemeral: whatever it writes is lost on recreation, unless you use [volumes](guide:volume).

## Example

```yaml
containers:
  - name: orders
    image: quay.io/acme/orders:2.4.1
    imagePullPolicy: IfNotPresent
    ports:
      - containerPort: 8080
    env:
      - name: LOG_LEVEL
        value: info
    resources:
      requests: { cpu: 200m, memory: 256Mi }
      limits: { memory: 512Mi }
```

```bash
# Shell alternative (Podman)
podman ps -a --format "{{.Names}} {{.Status}} {{.Image}}"
podman inspect orders --format "{{.State.ExitCode}} {{.State.OOMKilled}}"
podman logs --tail 200 orders
```

## What can go wrong

- Image does not exist or registry not authorized: [ImagePullBackOff](guide:imagepullbackoff).
- The process exits immediately: [CrashLoopBackOff](guide:crashloopbackoff).
- Exceeds its memory limit: [OOMKilled](guide:oomkilled) (exit code 137).
- Data written to the container filesystem lost at every restart.
- On Podman: a stopped container with no restart policy, which does not come back after a host reboot.

## How to verify

- Pod: **Panoramica** tab (state, last exit code, restarts) and **Log** tab choosing the container.
- Podman: [Container](app:/podman/containers) with state, image, ports; detail with logs and metrics.
- [Immagini](app:/podman/images) to see the tags and digests present on the host.

## How to fix

- Read the `reason` and exit code of the last termination, then the logs of the previous container.
- Use versioned tags or digests, never `latest` in production.
- For data that must survive, mount a volume or a [PersistentVolumeClaim](guide:persistent-volume-claim).
- On Podman, for containers that must survive reboots, use a systemd unit (Quadlet) or `--restart=always` with `podman-restart.service` enabled.
