---
title: Storage Class
summary: Describes a type of storage and lets disks be created automatically on demand.
category: storage
order: 40
keywords: storage class, storageclass, provisioner, csi, dynamic provisioning, default, volumeBindingMode
related: persistent-volume, persistent-volume-claim, volume, statefulset
---

## In simple terms

A **Storage Class** is a storage "price list": "class `standard` = SAN disks, class `fast` = SSD, class `nfs` = network share". When an application creates a [PVC](guide:persistent-volume-claim) naming a class, that class's **provisioner** automatically creates the disk and the corresponding [Persistent Volume](guide:persistent-volume).

Without a Storage Class an administrator must prepare PVs by hand, one by one.

## Technical details

- `provisioner`: the driver that creates volumes, usually a **CSI** driver (e.g. `driver.longhorn.io`, `nfs.csi.k8s.io`, `csi.vsphere.vmware.com`). The driver must be installed in the cluster. `kubernetes.io/no-provisioner` denotes manually created local volumes.
- `parameters`: driver-specific options (disk type, pool, filesystem, number of replicas).
- `reclaimPolicy`: `Delete` (default) or `Retain`, inherited by the created PVs.
- `volumeBindingMode`: `Immediate` (the disk is created right away) or `WaitForFirstConsumer` (created when a Pod uses the PVC, so it honors node/zone constraints; required for local volumes).
- `allowVolumeExpansion: true`: allows PVCs to be enlarged.
- `mountOptions`: mount options (e.g. `nfsvers=4.1`).
- **Default class**: annotation `storageclass.kubernetes.io/is-default-class: "true"`. There should be at most one; with several defaults behavior is ambiguous (the most recent one is chosen).
- Storage Classes are cluster-scoped and largely immutable: to change `parameters` or `provisioner` you create a new class.

In Scarlet: [Storage → Storage Classes](app:/k8s/storageclasses); the default class is highlighted.

## Example

```yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: nfs
  annotations:
    storageclass.kubernetes.io/is-default-class: "true"
provisioner: nfs.csi.k8s.io
parameters:
  server: nfs01.example.local
  share: /exports/k8s
reclaimPolicy: Retain
volumeBindingMode: Immediate
allowVolumeExpansion: true
mountOptions:
  - nfsvers=4.1
```

## What can go wrong

- **No default class**: PVCs without `storageClassName` stay Pending forever.
- **Provisioner not installed or failing**: PVCs Pending with `ProvisioningFailed` events or simply "waiting for a volume to be created by external provisioner".
- **Two default classes** at the same time.
- **Reclaim policy `Delete`** used for important data: deleting the PVC loses the disk.
- **Wrong parameters** (non-existent pool, expired storage backend credentials).

## How to verify

```bash
kubectl get storageclass
kubectl describe storageclass nfs
kubectl get csidrivers
kubectl get pods -A | grep -i csi
```

In Scarlet check that exactly one class is marked as default and that the CSI driver Pods are Running on the [Pod](app:/k8s/pods) page.

## How to fix

1. If there is no default class, an administrator can mark one: `kubectl patch storageclass nfs -p '{"metadata":{"annotations":{"storageclass.kubernetes.io/is-default-class":"true"}}}'`.
2. If there are two, remove the annotation from one of them.
3. If the provisioner does not respond, read its Pods' logs (CSI controller) from the Log tab.
4. For critical data create a class with `reclaimPolicy: Retain` and use it for new PVCs.
5. For PVCs already Pending see [Persistent Volume Claim](guide:persistent-volume-claim).
