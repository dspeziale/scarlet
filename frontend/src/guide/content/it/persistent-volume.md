---
title: Persistent Volume
summary: Una porzione di storage reale del cluster, disponibile per essere assegnata a un'applicazione.
category: storage
order: 20
keywords: persistent volume, pv, reclaim policy, access mode, csi, nfs, bound, released
related: persistent-volume-claim, storage-class, volume, statefulset, backup
---

## In parole semplici

Un **Persistent Volume (PV)** rappresenta un "disco" reale messo a disposizione del cluster: un LUN iSCSI, una condivisione NFS, un disco cloud, una cartella locale su un nodo. Le applicazioni non lo usano direttamente: lo richiedono tramite un [Persistent Volume Claim](guide:persistent-volume-claim) e Kubernetes associa la richiesta a un PV adatto.

I PV sono risorse **di cluster**, non appartengono a nessun namespace. Di solito non si creano a mano: li crea automaticamente una [Storage Class](guide:storage-class) (provisioning dinamico).

## Dettagli tecnici

- `spec.capacity.storage`: dimensione, es. `20Gi`.
- `spec.accessModes`: `ReadWriteOnce` (RWO, montabile in scrittura da un solo nodo), `ReadOnlyMany` (ROX), `ReadWriteMany` (RWX, più nodi in scrittura, es. NFS/CephFS), `ReadWriteOncePod` (un solo Pod).
- `spec.persistentVolumeReclaimPolicy`: cosa succede quando il PVC viene cancellato. `Delete` (default per i PV dinamici) **cancella anche il disco e i dati**; `Retain` conserva il disco, che va recuperato a mano.
- `spec.storageClassName`, `spec.volumeMode` (`Filesystem` o `Block`), `spec.nodeAffinity` (obbligatoria per i volumi `local`).
- Sorgente: `csi` (driver CSI, il modo moderno), `nfs`, `local`, `hostPath` (solo test).
- **Fasi** (`status.phase`): `Available` (libero), `Bound` (legato a un PVC), `Released` (il PVC è stato cancellato ma il PV con `Retain` non è ancora riutilizzabile), `Failed` (recupero automatico fallito).
- `spec.claimRef` indica il PVC a cui è legato.

In PKM: [Storage → Persistent Volumes](app:/k8s/persistentvolumes); la pagina [Monitoraggio → Storage](app:/monitoring/storage) riepiloga capacità e stati.

## Esempio

PV statico su NFS, creato da un amministratore:

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

## Cosa può andare storto

- **Dati cancellati** perché il PV aveva reclaim policy `Delete` e qualcuno ha eliminato il PVC.
- **PV in `Released`** che non può essere riassegnato: contiene ancora il riferimento al vecchio PVC.
- **PV in `Failed`**: il plugin non è riuscito a cancellare o ripulire il volume.
- **Nessun PV compatibile**: capacità, access mode o storageClassName non corrispondono al PVC, che resta Pending.
- **Errori di montaggio** sul nodo (server NFS irraggiungibile, pacchetto `nfs-utils` mancante su Oracle Linux, driver CSI non in esecuzione).

## Come verificare

```bash
kubectl get pv
kubectl describe pv nfs-reports
kubectl get pv -o custom-columns=NAME:.metadata.name,RECLAIM:.spec.persistentVolumeReclaimPolicy,STATUS:.status.phase,CLAIM:.spec.claimRef.name
```

In PKM controlla fase, reclaim policy e PVC collegato nella pagina di dettaglio (scheda Relazioni).

## Come risolvere

1. Per i dati importanti imposta `Retain` sui PV esistenti (si può cambiare anche dopo la creazione): `kubectl patch pv <nome> -p '{"spec":{"persistentVolumeReclaimPolicy":"Retain"}}'`.
2. Per riutilizzare un PV `Released`, dopo aver salvato o ripulito i dati, un amministratore rimuove `spec.claimRef` dalla scheda YAML.
3. Per gli errori di montaggio controlla il driver CSI ([DaemonSet](guide:daemonset)) e la raggiungibilità dello storage dal nodo.
4. Ricorda che i dati dei PV **non** sono inclusi nei backup di PKM: vedi [Backup](guide:backup).
