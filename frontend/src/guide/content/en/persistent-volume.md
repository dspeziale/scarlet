---
title: Persistent Volume
summary: A piece of real cluster storage, available to be assigned to an application.
category: storage
order: 20
keywords: persistent volume, pv, reclaim policy, access mode, csi, nfs, bound, released
related: persistent-volume-claim, storage-class, volume, statefulset, backup
---

## In simple terms

A **Persistent Volume (PV)** represents a real "disk" made available to the cluster: an iSCSI LUN, an NFS share, a cloud disk, a local directory on a node. Applications do not use it directly: they request it through a [Persistent Volume Claim](guide:persistent-volume-claim) and Kubernetes matches the request with a suitable PV.

PVs are **cluster-scoped** resources; they belong to no namespace. Usually they are not created by hand: a [Storage Class](guide:storage-class) creates them automatically (dynamic provisioning).

## Technical details

- `spec.capacity.storage`: size, e.g. `20Gi`.
- `spec.accessModes`: `ReadWriteOnce` (RWO, mountable read-write by a single node), `ReadOnlyMany` (ROX), `ReadWriteMany` (RWX, read-write from many nodes, e.g. NFS/CephFS), `ReadWriteOncePod` (a single Pod).
- `spec.persistentVolumeReclaimPolicy`: what happens when the PVC is deleted. `Delete` (default for dynamic PVs) **also deletes the disk and the data**; `Retain` keeps the disk, which must be reclaimed manually.
- `spec.storageClassName`, `spec.volumeMode` (`Filesystem` or `Block`), `spec.nodeAffinity` (mandatory for `local` volumes).
- Source: `csi` (CSI driver, the modern way), `nfs`, `local`, `hostPath` (testing only).
- **Phases** (`status.phase`): `Available` (free), `Bound` (bound to a PVC), `Released` (the PVC was deleted but the `Retain` PV is not reusable yet), `Failed` (automatic reclamation failed).
- `spec.claimRef` points to the bound PVC.

In PKM: [Storage → Persistent Volumes](app:/k8s/persistentvolumes); the [Monitoraggio → Storage](app:/monitoring/storage) page summarizes capacity and states.

## Example

Static NFS PV, created by an administrator:

```yaml
apiVersion: v1
kind: PersistentVolume
metadata:
  name: nfs-reports
spec:
  capacity:
    storage: 50Gi
  accessModes: [ReadWriteMany]
  persistentVolumeReclaimPolicy: Retain
  storageClassName: nfs-static
  mountOptions: [nfsvers=4.1]
  nfs:
    server: nfs01.example.local
    path: /exports/reports
```

## What can go wrong

- **Data deleted** because the PV had reclaim policy `Delete` and someone deleted the PVC.
- **PV stuck in `Released`** that cannot be reassigned: it still references the old PVC.
- **PV in `Failed`**: the plugin could not delete or clean the volume.
- **No compatible PV**: capacity, access mode or storageClassName do not match the PVC, which stays Pending.
- **Mount errors** on the node (unreachable NFS server, missing `nfs-utils` package on Oracle Linux, CSI driver not running).

## How to verify

```bash
kubectl get pv
kubectl describe pv nfs-reports
kubectl get pv -o custom-columns=NAME:.metadata.name,RECLAIM:.spec.persistentVolumeReclaimPolicy,STATUS:.status.phase,CLAIM:.spec.claimRef.name
```

In PKM check phase, reclaim policy and bound PVC on the detail page (Relazioni tab).

## How to fix

1. For important data set `Retain` on existing PVs (it can be changed after creation): `kubectl patch pv <name> -p '{"spec":{"persistentVolumeReclaimPolicy":"Retain"}}'`.
2. To reuse a `Released` PV, after saving or wiping the data, an administrator removes `spec.claimRef` from the YAML tab.
3. For mount errors check the CSI driver ([DaemonSet](guide:daemonset)) and storage reachability from the node.
4. Remember that PV data is **not** included in PKM backups: see [Backup](guide:backup).
