---
title: Persistent Volume Claim
summary: La richiesta di spazio disco persistente fatta da un'applicazione.
category: storage
order: 30
keywords: pvc, persistent volume claim, pending, bound, espansione, waitforfirstconsumer
related: persistent-volume, storage-class, volume, statefulset, pending
---

## In parole semplici

Un **Persistent Volume Claim (PVC)** è un "buono" per avere spazio disco: "mi servono 20 GiB, in lettura e scrittura, di classe `standard`". Kubernetes cerca o crea un [Persistent Volume](guide:persistent-volume) che soddisfi la richiesta e li lega insieme (*bind*). Da quel momento il Pod può usare il PVC come volume.

Il PVC vive in un namespace, come l'applicazione che lo usa. Il disco sopravvive anche se il Pod viene cancellato o spostato.

## Dettagli tecnici

- `spec.resources.requests.storage`: dimensione richiesta.
- `spec.accessModes`: deve essere supportato dalla [Storage Class](guide:storage-class) (molti storage a blocchi offrono solo `ReadWriteOnce`).
- `spec.storageClassName`: classe da usare. Se omesso si usa la classe di default; se impostato a `""` si chiede esplicitamente un PV senza classe (solo statico).
- **Fasi**: `Pending` (non ancora legato), `Bound` (legato a un PV), `Lost` (il PV associato non esiste più).
- Con `volumeBindingMode: WaitForFirstConsumer` il PVC resta `Pending` **finché un Pod non lo usa**: è normale, il disco viene creato nella zona/nodo dove il Pod viene schedulato.
- **Espansione**: si può aumentare `requests.storage` se la Storage Class ha `allowVolumeExpansion: true`. Non è possibile ridurre.
- **Protezione**: un PVC in uso da un Pod ha il finalizer `kubernetes.io/pvc-protection` e resta in `Terminating` finché il Pod esiste.
- Con `ReadWriteOnce` due Pod su nodi diversi non possono montarlo: il secondo resta in `ContainerCreating` con `Multi-Attach error`.

In Scarlet: [Storage → Persistent Volume Claims](app:/k8s/persistentvolumeclaims). Il [Centro Operativo](app:/operations-center) segnala i PVC Pending.

## Esempio

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

## Cosa può andare storto

- **PVC Pending**: nessuna Storage Class di default, nome della classe errato, provisioner non installato o in errore, quota di storage del namespace superata, access mode non supportato.
- **Pod Pending** a causa del PVC: lo scheduler non trova un nodo compatibile con il volume (affinità di zona o di nodo).
- **Multi-Attach error** durante un rolling update di un Deployment con PVC RWO: il nuovo Pod nasce su un altro nodo mentre il vecchio tiene ancora il disco.
- **Disco pieno**: l'applicazione riceve "No space left on device".
- **PVC bloccato in Terminating** perché ancora in uso.

## Come verificare

In Scarlet apri il PVC: fase, PV associato, Storage Class, capacità e, nella scheda Eventi, i messaggi del provisioner (es. `ProvisioningFailed`).

```bash
kubectl -n shop get pvc web-uploads
kubectl -n shop describe pvc web-uploads
kubectl get storageclass
```

## Come risolvere

1. Leggi gli eventi del PVC: `no persistent volumes available` (nessun PV e nessun provisioner), `ProvisioningFailed` (errore del driver), `waiting for first consumer` (normale).
2. Indica una `storageClassName` esistente o definisci una classe di default.
3. Per i Deployment con PVC RWO usa la strategia `Recreate` o passa a uno [StatefulSet](guide:statefulset).
4. Per aumentare lo spazio modifica `requests.storage` dalla scheda YAML (serve `allowVolumeExpansion`).
5. Per un Pod bloccato in Pending vedi [Pending](guide:pending).
