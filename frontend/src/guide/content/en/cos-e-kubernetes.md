---
title: What Kubernetes is
summary: The platform that runs containers across many machines and keeps applications in their desired state.
category: intro
order: 20
keywords: kubernetes, k8s, orchestrator, control plane, api server, kubectl, desired state
related: cluster, node, pod, deployment, cos-e-podman, namespace
---

## In simple terms

Kubernetes is a **container orchestrator**: it takes your applications packaged as containers and runs them on a group of machines (the [cluster](guide:cluster)), deciding where to place them, restarting them when they hang, and replacing them when a machine fails.

The key idea is **desired state**. You do not say "start this container on that machine"; you say "I want 3 copies of this application, with this image, reachable on this port". Kubernetes continuously compares what you asked for with what is actually happening and fixes the differences by itself.

## Technical details

A Kubernetes cluster is made of:

- **Control plane**: `kube-apiserver` (the single entry point, exposing the REST APIs), `etcd` (the key-value database holding the entire cluster state), `kube-scheduler` (assigns pods to nodes), `kube-controller-manager` (runs the controllers that reconcile state: Deployment, ReplicaSet, Node, Job...).
- **Worker nodes**: each [node](guide:node) runs `kubelet` (starts and monitors containers through the runtime, usually containerd or CRI-O), `kube-proxy` (network rules for Services) and a CNI network plugin.

Everything in Kubernetes is an **API object** described in YAML or JSON with four parts: `apiVersion`, `kind`, `metadata` (name, namespace, labels, annotations) and `spec` (the desired state). Kubernetes adds `status` (the observed state). Controllers work in a **reconciliation** loop: they read `spec`, observe reality, and act to bring the two closer.

The main objects you will use: [Pod](guide:pod), [Deployment](guide:deployment), [StatefulSet](guide:statefulset), [DaemonSet](guide:daemonset), [Job](guide:job), [Service](guide:service), [Ingress](guide:ingress), [ConfigMap](guide:configmap), [Secret](guide:secret), [PersistentVolumeClaim](guide:persistent-volume-claim). Objects are grouped into [namespaces](guide:namespace).

Access is controlled by **RBAC**: Role/ClusterRole define what can be done, RoleBinding/ClusterRoleBinding define who is granted it. PKM connects with a kubeconfig, ideally for a dedicated ServiceAccount, and can only do what that ServiceAccount is authorized to do.

## Example

A minimal Deployment requesting three copies of a web server:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: web
  namespace: demo
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
        - name: nginx
          image: nginx:1.27
          ports:
            - containerPort: 80
```

Shell alternative (for administrators):

```bash
kubectl apply -f web.yaml
kubectl get deployment web -n demo
kubectl get pods -n demo -l app=web -o wide
```

## What can go wrong

- **API server unreachable**: PKM and `kubectl` can neither read nor change anything. Applications already running usually keep running, but nothing gets reconciled.
- **Insufficient RBAC permissions**: operations rejected with a `Forbidden` error.
- **Impossible desired state**: for example resource requests larger than node capacity; pods stay [Pending](guide:pending).
- **Nodes not ready**: see [Node NotReady](guide:node-notready).

## How to verify

- In PKM open [Cluster → Panoramica](app:/cluster): version, number of nodes, component status.
- Check the [Health](app:/monitoring/health) page: the Kubernetes entry must be Healthy.
- From a shell:

```bash
kubectl cluster-info
kubectl get nodes
kubectl get --raw='/readyz?verbose'
```

## How to fix

- If the connection fails, check the kubeconfig in [Impostazioni → Kubernetes](app:/settings/kubernetes) and follow [Connecting Kubernetes](guide:proc-collegare-kubernetes).
- If you get `Forbidden`, the ServiceAccount used by PKM lacks permissions: a cluster administrator must update the ClusterRole.
- For problems with individual resources, start from the [Operations Center](app:/operations-center) and follow the method described in [Troubleshooting](guide:troubleshooting).
