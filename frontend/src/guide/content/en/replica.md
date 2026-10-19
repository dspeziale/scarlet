---
title: Replicas
summary: Several identical copies of the same Pod to handle load and survive failures.
category: reliability
order: 10
keywords: replicas, replica, scale, scaling, hpa, redundancy
related: deployment, replicaset, statefulset, alta-disponibilita, proc-scalare
---

## In simple terms

A **replica** is an identical copy of a Pod. If an application runs with three replicas, Kubernetes always keeps three identical Pods running: if one stops, the controller creates another one. More replicas mean more capacity to serve requests and less risk that a single failure takes the service down.

Think of a counter with three clerks instead of one: if one takes a break, the others keep serving.

## Technical details

- The desired number is in the `spec.replicas` field of Deployments, StatefulSets and ReplicaSets. The actual values are in `status.replicas`, `status.readyReplicas` and `status.availableReplicas`.
- The **ReplicaSet** (managed by a Deployment) continuously compares desired and actual state and creates or deletes Pods to make them match (reconciliation).
- Deployment replicas are **interchangeable**: random names, no stable identity. StatefulSet replicas have stable names and storage (`db-0`, `db-1`, ...).
- A **Service** sends traffic only to *Ready* replicas (see [Readiness probe](guide:readiness-probe)).
- Scaling can be manual (`spec.replicas`) or automatic with a **HorizontalPodAutoscaler** (HPA), which requires metrics-server. If an HPA manages the workload, a manual change of replicas will be overwritten.
- A DaemonSet has no `replicas`: it creates one Pod per eligible node.

More replicas alone are not high availability: if they all land on the same node, losing that node stops all of them. You also need spreading rules (see [High availability](guide:alta-disponibilita)).

## Example

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: web
  namespace: shop
spec:
  replicas: 3
  selector:
    matchLabels:
      app: web
  template:
    metadata:
      labels:
        app: web
    spec:
      containers:
        - name: web
          image: registry.example.com/shop/web:1.4.2
```

Shell alternative (for administrators):

```bash
kubectl -n shop scale deployment/web --replicas=5
kubectl -n shop get deployment web
```

## What can go wrong

- **Replicas not ready**: `READY 1/3` means Pods in `Pending`, `CrashLoopBackOff` or with a failing readiness probe.
- **Insufficient resources**: when you add replicas, new Pods stay `Pending` if no node has the requested CPU/RAM available.
- **Scaling reverted**: an HPA or a GitOps pipeline brings the value back to the configured one.
- **Application not designed for multiple copies**: in-memory sessions, internal scheduled jobs or locally written files can cause inconsistent behavior.
- **A single replica**: any restart, update or node maintenance causes an outage.

## How to verify

- In [Deployments](app:/k8s/deployments) the replicas column shows ready/desired; the **Panoramica** tab of the detail page shows status and the **Relazioni** tab shows the linked Pods.
- In [Pod](app:/k8s/pods) filter by namespace and check which nodes the replicas run on.
- The [Centro Operativo](app:/operations-center) flags degraded deployments.

```bash
kubectl -n shop get deploy web -o wide
kubectl -n shop get pods -l app=web -o wide
kubectl -n shop get hpa
```

## How to fix

1. If ready replicas are fewer than desired, open the non-ready Pods and follow [Troubleshooting](guide:troubleshooting) (**Diagnostica** and **Eventi** tabs).
2. To change the replica count use [Operazioni → Scale](app:/operations/scale) (see [Scale an application](guide:proc-scalare)).
3. If there is an HPA, change `minReplicas`/`maxReplicas` instead of `replicas`.
4. For important services use at least 2-3 replicas and spread them across different nodes.
