---
title: StatefulSet
summary: Esegue applicazioni con identità stabile e dati propri, come database e code di messaggi.
category: workloads
order: 30
keywords: statefulset, database, identità stabile, volumeClaimTemplates, headless service, ordinal
related: deployment, persistent-volume-claim, storage-class, service, pod, backup
---

## In parole semplici

Un **StatefulSet** è simile a un [Deployment](guide:deployment), ma pensato per applicazioni che **ricordano qualcosa**: database, broker di messaggi, cluster come etcd o Elasticsearch. Ogni Pod ha un **nome fisso** (`db-0`, `db-1`, `db-2`) e un **disco tutto suo** che lo segue anche quando viene ricreato su un altro nodo.

Se `db-1` muore, Kubernetes ricrea esattamente `db-1`, con lo stesso nome e lo stesso volume. Con un Deployment, invece, i Pod sono intercambiabili e hanno nomi casuali.

## Dettagli tecnici

- **Identità stabile**: i Pod si chiamano `<nome>-<ordinale>` con ordinale da 0 a N-1.
- **DNS stabile**: richiede un [Service](guide:service) *headless* (`clusterIP: None`) indicato in `spec.serviceName`. Ogni Pod è raggiungibile come `db-0.db.<namespace>.svc.cluster.local`.
- **Storage per Pod**: `spec.volumeClaimTemplates` genera un [PVC](guide:persistent-volume-claim) per ogni Pod, chiamato `<template>-<nome>-<ordinale>` (es. `data-db-0`). I PVC **non vengono cancellati** quando riduci le repliche o elimini lo StatefulSet (salvo diversa `persistentVolumeClaimRetentionPolicy`).
- **Ordine**: con `podManagementPolicy: OrderedReady` (default) i Pod vengono creati in ordine 0→N-1, ciascuno solo quando il precedente è Ready, e rimossi in ordine inverso. `Parallel` elimina questo vincolo.
- **Aggiornamenti**: `updateStrategy.type: RollingUpdate` aggiorna dal Pod con ordinale più alto al più basso; `rollingUpdate.partition` permette aggiornamenti a stadi (canary). `OnDelete` aggiorna un Pod solo quando lo cancelli tu.

In PKM: [Applicazioni → StatefulSets](app:/k8s/statefulsets). La scheda Relazioni mostra Pod e PVC collegati.

## Esempio

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: db
  namespace: shop
spec:
  serviceName: db
  replicas: 3
  selector:
    matchLabels: { app: db }
  template:
    metadata:
      labels: { app: db }
    spec:
      containers:
        - name: postgres
          image: docker.io/library/postgres:16
          ports: [{ containerPort: 5432 }]
          volumeMounts:
            - { name: data, mountPath: /var/lib/postgresql/data }
  volumeClaimTemplates:
    - metadata:
        name: data
      spec:
        accessModes: [ReadWriteOnce]
        storageClassName: standard
        resources:
          requests:
            storage: 20Gi
```

## Cosa può andare storto

- **Pod fermo in [Pending](guide:pending)** perché il suo PVC è Pending (nessuna StorageClass, nessun PV disponibile) o perché il volume è legato a una zona/nodo non disponibile.
- **Avvio bloccato a metà**: con `OrderedReady`, se `db-1` non diventa mai Ready, `db-2` non viene mai creato.
- **Nodo guasto**: un Pod di StatefulSet su un nodo [NotReady](guide:node-notready) resta in `Terminating`/`Unknown` e Kubernetes **non** ne crea una copia altrove finché non è certo che il vecchio sia morto, per evitare due istanze che scrivono sullo stesso disco.
- **Dati persi** se elimini a mano i PVC credendo che siano "spazzatura".

## Come verificare

In PKM controlla repliche pronte, poi Pod e PVC nella scheda Relazioni; in [Storage → Persistent Volume Claims](app:/k8s/persistentvolumeclaims) verifica che i PVC siano `Bound`.

```bash
kubectl -n shop get statefulset db
kubectl -n shop get pods -l app=db -o wide
kubectl -n shop get pvc -l app=db
kubectl -n shop rollout status statefulset/db
```

## Come risolvere

1. Se un PVC è Pending, risolvi prima lo storage: vedi [Persistent Volume Claim](guide:persistent-volume-claim).
2. Se un Pod non diventa Ready, diagnosticalo come un qualsiasi Pod ([procedura](guide:proc-diagnosticare-pod)); gli altri ordinali attendono.
3. In caso di nodo perso definitivamente, un amministratore può, dopo aver verificato che il nodo sia davvero spento, forzare la cancellazione del Pod (`kubectl delete pod db-1 --grace-period=0 --force`): è un'operazione rischiosa.
4. Prima di ridurre le repliche o cancellare PVC fai un [backup](guide:backup) dei dati applicativi: PKM non salva il contenuto dei volumi.
