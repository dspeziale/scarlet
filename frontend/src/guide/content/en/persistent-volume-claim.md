---
title: Persistent Volume Claim
summary: An application's request for persistent disk space.
category: storage
order: 30
keywords: pvc, persistent volume claim, pending, bound, expansion, waitforfirstconsumer
related: persistent-volume, storage-class, volume, statefulset, pending
---

## In simple terms

A **Persistent Volume Claim (PVC)** is a "voucher" for disk space: "I need 20 GiB, read-write, of class `standard`". Kubernetes finds or creates a [Persistent Volume](guide:persistent-volume) that satisfies the request and binds them together. From then on, the Pod can use the PVC as a volume.

The PVC lives in a namespace, like the application that uses it. The disk survives even if the Pod is deleted or moved.

## Technical details

- `spec.resources.requests.storage`: requested size.
- `spec.accessModes`: must be supported by the [Storage Class](guide:storage-class) (many block storage systems offer only `ReadWriteOnce`).
- `spec.storageClassName`: class to use. If omitted, the default class is used; if set to `""` you explicitly ask for a PV without a class (static only).
- **Phases**: `Pending` (not bound yet), `Bound` (bound to a PV), `Lost` (the bound PV no longer exists).
- With `volumeBindingMode: WaitForFirstConsumer` the PVC stays `Pending` **until a Pod uses it**: this is normal, the disk is created in the zone/node where the Pod gets scheduled.
- **Expansion**: you can increase `requests.storage` if the Storage Class has `allowVolumeExpansion: true`. Shrinking is not possible.
- **Protection**: a PVC in use by a Pod has the `kubernetes.io/pvc-protection` finalizer and stays `Terminating` while the Pod exists.
- With `ReadWriteOnce` two Pods on different nodes cannot mount it: the second stays in `ContainerCreating` with a `Multi-Attach error`.

In Scarlet: [Storage → Persistent Volume Claims](app:/k8s/persistentvolumeclaims). The [Centro Operativo](app:/operations-center) flags Pending PVCs.

## Example

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: web-uploads
  namespace: shop
spec:
  accessModes: [ReadWriteOnce]
  storageClassName: standard
  resources:
    requests:
      storage: 10Gi
```

## What can go wrong

- **PVC Pending**: no default Storage Class, wrong class name, provisioner not installed or failing, namespace storage quota exceeded, unsupported access mode.
- **Pod Pending** because of the PVC: the scheduler finds no node compatible with the volume (zone or node affinity).
- **Multi-Attach error** during a rolling update of a Deployment with an RWO PVC: the new Pod starts on another node while the old one still holds the disk.
- **Disk full**: the application gets "No space left on device".
- **PVC stuck in Terminating** because it is still in use.

## How to verify

In Scarlet open the PVC: phase, bound PV, Storage Class, capacity and, in the Eventi tab, the provisioner messages (e.g. `ProvisioningFailed`).

```bash
kubectl -n shop get pvc web-uploads
kubectl -n shop describe pvc web-uploads
kubectl get storageclass
```

## How to fix

1. Read the PVC events: `no persistent volumes available` (no PV and no provisioner), `ProvisioningFailed` (driver error), `waiting for first consumer` (normal).
2. Specify an existing `storageClassName` or define a default class.
3. For Deployments with RWO PVCs use the `Recreate` strategy or switch to a [StatefulSet](guide:statefulset).
4. To increase space change `requests.storage` from the YAML tab (requires `allowVolumeExpansion`).
5. For a Pod stuck in Pending see [Pending](guide:pending).
