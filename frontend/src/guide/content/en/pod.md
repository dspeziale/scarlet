---
title: Pod
summary: The smallest unit Kubernetes runs, made of one or more containers sharing network and volumes.
category: concepts
order: 40
keywords: pod, phases, pending, running, succeeded, failed, unknown, restart, ready, init container
related: container, deployment, node, scheduling, troubleshooting, proc-diagnosticare-pod, pod-failed-unknown
---

## In simple terms

A pod is the "box" in which Kubernetes runs your application. It usually holds a single container; sometimes a main container plus a few helper containers (for example a proxy or a log collector).

Pods are **disposable**: if a pod dies or its node fails, Kubernetes does not repair it; it creates a new one (with a different name and IP). This is why you almost never create pods by hand: they are created by a [Deployment](guide:deployment), a [StatefulSet](guide:statefulset), a [DaemonSet](guide:daemonset) or a [Job](guide:job).

## Technical details

The containers of a pod share the same network namespace (same IP, they talk on `localhost`) and can mount the same [volumes](guide:volume). A pod always runs entirely on a single [node](guide:node).

**Pod phases** (`status.phase`):

| Phase | Meaning |
|---|---|
| Pending | Accepted but not yet started: waiting for scheduling, image pull or volumes |
| Running | Bound to a node, at least one container running |
| Succeeded | All containers terminated successfully (typical of Jobs) |
| Failed | All containers terminated, at least one with an error |
| Unknown | The state cannot be obtained, usually because the node is not responding |

States such as `CrashLoopBackOff`, `ImagePullBackOff`, `CreateContainerConfigError` **are not phases**: they are `reason` values of a container's `waiting` state, shown in the STATUS column of `kubectl get pods`.

**Conditions**: `PodScheduled`, `Initialized`, `ContainersReady`, `Ready`. Only `Ready` pods receive traffic from [Services](guide:service), and Ready depends on the [readiness probe](guide:readiness-probe).

**restartPolicy**: `Always` (default, mandatory in Deployments), `OnFailure`, `Never` (used in Jobs). Restarts use an exponential backoff capped at 5 minutes.

**Init containers** run in sequence before the main containers and must complete successfully.

## Example

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: debug-tools
  namespace: staging
spec:
  restartPolicy: Never
  containers:
    - name: tools
      image: registry.access.redhat.com/ubi9/ubi-minimal:latest
      command: ["sleep", "3600"]
      resources:
        requests: { cpu: 50m, memory: 64Mi }
        limits: { memory: 128Mi }
```

```bash
# Shell alternative
kubectl get pods -n staging -o wide
kubectl describe pod debug-tools -n staging
kubectl logs debug-tools -n staging --previous
```

## What can go wrong

- Stays [Pending](guide:pending): no suitable node, unbound PVC, quota exceeded.
- [ImagePullBackOff / ErrImagePull](guide:imagepullbackoff): wrong image or credentials.
- [CrashLoopBackOff](guide:crashloopbackoff): the process exits right after starting.
- [OOMKilled](guide:oomkilled): exceeds its memory limit.
- [CreateContainerConfigError](guide:createcontainerconfigerror): missing ConfigMap or Secret.
- Running but not Ready: failing readiness probe.
- [Failed or Unknown](guide:pod-failed-unknown).

## How to verify

- [Applicazioni → Pod](app:/k8s/pods): status, ready, restarts, node, age.
- Pod detail: **Panoramica** (container state and last termination reason), **Eventi**, **Log** (including the previous container), **Diagnostica**.
- Procedure: [Diagnosing a pod](guide:proc-diagnosticare-pod).

## How to fix

- Read the **Eventi** first, then the **Log** (of the previous container, if it restarted). The reason is almost always there.
- Fix the cause in the controller (Deployment, StatefulSet...) and not in the pod: changes made to the pod are lost when it is recreated.
- A restart from [Operazioni → Restart](app:/operations/restart) recreates the pods, but **does not fix** configuration problems: use it only once the cause has been removed.
- If the problem started with a release, consider a [rollback](guide:rollback).
