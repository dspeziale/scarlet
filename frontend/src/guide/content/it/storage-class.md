---
title: Storage Class
summary: Descrive un tipo di storage e permette di creare dischi automaticamente su richiesta.
category: storage
order: 40
keywords: storage class, storageclass, provisioner, csi, provisioning dinamico, default, volumeBindingMode
related: persistent-volume, persistent-volume-claim, volume, statefulset
---

## In parole semplici

Una **Storage Class** è un "listino" dello storage: "classe `standard` = dischi su SAN, classe `fast` = SSD, classe `nfs` = condivisione di rete". Quando un'applicazione crea un [PVC](guide:persistent-volume-claim) indicando una classe, il **provisioner** di quella classe crea automaticamente il disco e il relativo [Persistent Volume](guide:persistent-volume).

Senza Storage Class un amministratore deve preparare i PV a mano, uno per uno.

## Dettagli tecnici

- `provisioner`: il driver che crea i volumi, di solito un driver **CSI** (es. `driver.longhorn.io`, `nfs.csi.k8s.io`, `csi.vsphere.vmware.com`). Il driver deve essere installato nel cluster. `kubernetes.io/no-provisioner` indica volumi locali creati a mano.
- `parameters`: opzioni specifiche del driver (tipo di disco, pool, filesystem, numero di repliche).
- `reclaimPolicy`: `Delete` (default) o `Retain`, ereditata dai PV creati.
- `volumeBindingMode`: `Immediate` (il disco viene creato subito) oppure `WaitForFirstConsumer` (creato quando un Pod usa il PVC, così rispetta i vincoli di nodo/zona; obbligatorio per i volumi locali).
- `allowVolumeExpansion: true`: consente di ingrandire i PVC.
- `mountOptions`: opzioni di mount (es. `nfsvers=4.1`).
- **Classe di default**: annotazione `storageclass.kubernetes.io/is-default-class: "true"`. Deve essercene al massimo una; con più default il comportamento è ambiguo (viene scelta la più recente).
- Le Storage Class sono oggetti di cluster e in gran parte immutabili: per cambiare `parameters` o `provisioner` si crea una nuova classe.

In PKM: [Storage → Storage Classes](app:/k8s/storageclasses); la classe di default è evidenziata.

## Esempio

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

## Cosa può andare storto

- **Nessuna classe di default**: i PVC senza `storageClassName` restano Pending per sempre.
- **Provisioner non installato o in errore**: PVC Pending con eventi `ProvisioningFailed` o semplicemente "waiting for a volume to be created by external provisioner".
- **Due classi di default** contemporaneamente.
- **Reclaim policy `Delete`** usata per dati importanti: cancellando il PVC si perde il disco.
- **Parametri errati** (pool inesistente, credenziali del backend storage scadute).

## Come verificare

```bash
kubectl get storageclass
kubectl describe storageclass nfs
kubectl get csidrivers
kubectl get pods -A | grep -i csi
```

In PKM controlla che una sola classe sia marcata come default e che i Pod del driver CSI siano Running nella pagina [Pod](app:/k8s/pods).

## Come risolvere

1. Se manca la classe di default, un amministratore può marcarne una: `kubectl patch storageclass nfs -p '{"metadata":{"annotations":{"storageclass.kubernetes.io/is-default-class":"true"}}}'`.
2. Se ce ne sono due, rimuovi l'annotazione da una delle due.
3. Se il provisioner non risponde, leggi i log dei suoi Pod (controller CSI) dalla scheda Log.
4. Per dati critici crea una classe con `reclaimPolicy: Retain` e usala per i nuovi PVC.
5. Per i PVC già Pending vedi [Persistent Volume Claim](guide:persistent-volume-claim).
