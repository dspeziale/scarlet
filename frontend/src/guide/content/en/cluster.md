---
title: Cluster
summary: The set of control plane and nodes that Kubernetes manages as a single platform.
category: concepts
order: 10
keywords: cluster, control plane, etcd, api server, context, kubeconfig
related: node, namespace, cos-e-kubernetes, proc-verificare-cluster, alta-disponibilita, backup
---

## In simple terms

A cluster is the "single computer" Kubernetes builds by combining many machines. You hand applications to the cluster, not to a specific machine: the cluster decides where to run them and keeps them alive.

In Scarlet, the [Cluster → Panoramica](app:/cluster) page gives you a snapshot of the cluster you are connected to: the context name (the same as in the LIVE badge), the Kubernetes version, how many nodes there are and whether they are ready, how many pods are running, and which problems are open.

## Technical details

A cluster has two parts:

- **Control plane**: `kube-apiserver`, `etcd`, `kube-scheduler`, `kube-controller-manager` (and, in clouds, `cloud-controller-manager`). In a production cluster the control plane has **at least three nodes**, because `etcd` uses a quorum (majority): with 3 members it tolerates losing 1, with 5 it tolerates losing 2.
- **Worker nodes**: run the pods. See [Node](guide:node).

The client (Scarlet, `kubectl`) connects to the API server using a **kubeconfig**, which contains the server address, the CA certificate and the credentials. A kubeconfig can hold multiple **contexts** (cluster + user + default namespace); Scarlet uses the one configured in [Impostazioni → Kubernetes](app:/settings/kubernetes).

All cluster state lives in `etcd`. This is why a real cluster backup is an **etcd snapshot** (or a tool such as Velero), which is different from the manifests export Scarlet offers: see [Backup](guide:backup).

Resources are either **namespaced** (Pod, Deployment, Service, ConfigMap, Secret, PVC...) or **cluster-scoped** (Node, PersistentVolume, StorageClass, Namespace, ClusterRole...).

## Example

```bash
# Shell alternative
kubectl config current-context
kubectl version
kubectl get nodes -o wide
kubectl get pods -A --field-selector=status.phase!=Running
kubectl get --raw='/readyz?verbose'
```

Excerpt of a kubeconfig:

```yaml
apiVersion: v1
kind: Config
clusters:
  - name: prod
    cluster:
      server: https://k8s-api.example.local:6443
      certificate-authority-data: LS0tLS1CRUdJTi...
contexts:
  - name: pkm@prod
    context:
      cluster: prod
      user: pkm
current-context: pkm@prod
```

## What can go wrong

- **API server unreachable**: network, firewall, expired certificates, control plane down. Scarlet shows Kubernetes as Unhealthy.
- **Loss of etcd quorum**: the API server becomes read-only or stops responding; no changes are possible.
- **Expired cluster certificates** (typical of kubeadm clusters not upgraded for a year).
- **Wrong context**: you are looking at (or changing) the wrong cluster.
- **NotReady nodes**: reduced capacity, pods to reschedule.

## How to verify

- [Cluster → Panoramica](app:/cluster) and [Health](app:/monitoring/health).
- [Cluster events](app:/cluster/events): filter by type Warning.
- Check the context name in the LIVE badge before every action.
- Full procedure: [Verifying the cluster](guide:proc-verificare-cluster).

## How to fix

- No connection: check network and firewall towards the API server port (usually 6443), then the kubeconfig in [Impostazioni → Kubernetes](app:/settings/kubernetes).
- Expired certificates or control plane issues: these are cluster administrator tasks (e.g. `kubeadm certs check-expiration`) and cannot be fixed from Scarlet.
- NotReady nodes: follow [Node NotReady](guide:node-notready).
- Wrong context: fix the configured kubeconfig and check the badge again.
