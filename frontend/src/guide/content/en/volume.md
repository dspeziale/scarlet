---
title: Volume
summary: Disk space mounted into a container, either temporary or persistent.
category: storage
order: 10
keywords: volume, emptydir, hostpath, configmap, secret, volumemounts, storage, disk
related: persistent-volume, persistent-volume-claim, storage-class, configmap, secret, container
---

## In simple terms

A container's filesystem is **disposable**: when the container restarts, everything written to it is gone. A **volume** is a directory "mounted" inside the container that survives at least container restarts; some types also survive deletion of the Pod.

You declare the volume at Pod level (`spec.volumes`) and mount it into one or more containers with `volumeMounts`, giving the path.

## Technical details

Most common types:

| Type | Lifetime | Typical use |
|---|---|---|
| `emptyDir` | Pod lifetime | cache, temporary files, sharing between containers |
| `configMap` / `secret` | tied to the object | configuration files, certificates |
| `persistentVolumeClaim` | independent of the Pod | application data, databases |
| `hostPath` | tied to the node | system agents; discouraged for applications |
| `projected` | Pod lifetime | combining tokens, ConfigMaps and Secrets |

- `emptyDir` can use RAM with `medium: Memory` (counted against the container memory limit) and can be capped with `sizeLimit`.
- `configMap` and `secret` volumes are updated automatically when the object changes (with a delay of some tens of seconds), **except** when mounted with `subPath`.
- `readOnly: true` on the `volumeMount` prevents writes.
- Persistent volumes are obtained through a [Persistent Volume Claim](guide:persistent-volume-claim), which the cluster binds to a [Persistent Volume](guide:persistent-volume).
- `hostPath` gives access to the node filesystem: it is a security risk and ties the Pod to that node.
- `securityContext.fsGroup` sets the group owning the volume files, useful when the container does not run as root.

## Example

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: web
  namespace: shop
spec:
  securityContext:
    fsGroup: 1000
  containers:
    - name: web
      image: registry.example.com/shop/web:1.4.2
      volumeMounts:
        - { name: cache, mountPath: /tmp/cache }
        - { name: config, mountPath: /etc/web, readOnly: true }
        - { name: uploads, mountPath: /data/uploads }
  volumes:
    - name: cache
      emptyDir: { sizeLimit: 500Mi }
    - name: config
      configMap: { name: web-config }
    - name: uploads
      persistentVolumeClaim: { claimName: web-uploads }
```

## What can go wrong

- **Data lost** because it was saved in `emptyDir` or in the container filesystem instead of a PVC.
- **`FailedMount` / `FailedAttachVolume`**: the volume does not mount (PVC not Bound, disk still attached to another node, CSI driver missing).
- **Permission denied** in the container: the process user has no permissions on the volume files.
- **Missing ConfigMap or Secret**: the Pod stays in `ContainerCreating` with a failed mount event.
- **Pod eviction** because an `emptyDir` fills the node disk (`ephemeral-storage`).

## How to verify

In PKM open the Pod: the Panoramica tab lists mounted volumes, the Eventi tab shows `FailedMount` with the reason, the Relazioni tab links PVCs, ConfigMaps and Secrets.

```bash
kubectl -n shop describe pod web | sed -n '/Volumes:/,/QoS/p'
kubectl -n shop get events --field-selector reason=FailedMount
kubectl -n shop exec web -- df -h /data/uploads
```

## How to fix

1. For `FailedMount` read the exact message: name of the missing object or driver error.
2. If the PVC is Pending, see [Persistent Volume Claim](guide:persistent-volume-claim).
3. For permission problems set `fsGroup` or `runAsUser` consistent with the image.
4. Move important data to a PVC; use `emptyDir` only for reproducible data, with `sizeLimit`.
5. Avoid `hostPath` for applications.
