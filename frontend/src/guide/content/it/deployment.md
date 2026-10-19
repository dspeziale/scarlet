---
title: Deployment
summary: Gestisce copie identiche della tua applicazione e le aggiorna progressivamente senza interruzioni.
category: workloads
order: 10
keywords: deployment, replicaset, rolling update, repliche, rollout, revisione
related: replicaset, pod, replica, rolling-update, rollback, readiness-probe, proc-pubblicare-applicazione, proc-scalare
---

## In parole semplici

Un **Deployment** è il modo standard per far girare un'applicazione *stateless* (che non conserva dati propri) su Kubernetes. Tu dichiari "voglio 3 copie di questa immagine, con queste risorse" e Kubernetes si occupa di crearle, di ricrearle se muoiono e di aggiornarle una alla volta quando cambi versione.

Non crei i Pod a mano: li crea il Deployment, tramite un oggetto intermedio chiamato [ReplicaSet](guide:replicaset). Se cancelli un Pod gestito da un Deployment, ne compare subito un altro: è il comportamento voluto, non un errore.

## Dettagli tecnici

- `spec.replicas`: numero di Pod desiderati.
- `spec.selector.matchLabels`: le etichette che identificano i Pod gestiti. Deve coincidere con `spec.template.metadata.labels` e **non è modificabile** dopo la creazione.
- `spec.template`: il modello del Pod (container, immagine, porte, probe, risorse). Ogni modifica al template genera una nuova **revisione** e un nuovo ReplicaSet; modificare solo `replicas` invece no.
- `spec.strategy`: `RollingUpdate` (predefinita, con `maxSurge` e `maxUnavailable`, default 25%) oppure `Recreate` (spegne tutti i Pod e poi crea quelli nuovi: c'è un'interruzione del servizio).
- `spec.revisionHistoryLimit` (default 10): quanti ReplicaSet vecchi conservare per il [rollback](guide:rollback).
- `spec.progressDeadlineSeconds` (default 600): oltre questo tempo senza progressi la condizione `Progressing` diventa `False` con motivo `ProgressDeadlineExceeded`. Il rollout non viene annullato automaticamente: serve un intervento.

Lo stato si legge in `status`: `replicas`, `updatedReplicas`, `readyReplicas`, `availableReplicas` e le condizioni `Available` e `Progressing`. Un Pod conta come "ready" solo quando la sua [readiness probe](guide:readiness-probe) ha successo.

In Scarlet trovi l'elenco in [Applicazioni → Deployments](app:/k8s/deployments); la pagina di dettaglio mostra repliche pronte/desiderate, i ReplicaSet collegati (scheda Relazioni), gli eventi e lo YAML.

## Esempio

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: web
  namespace: shop
spec:
  replicas: 3
  selector:
    matchLabels:
      app: web
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 0
  template:
    metadata:
      labels:
        app: web
    spec:
      containers:
        - name: web
          image: registry.example.com/shop/web:1.4.2
          ports:
            - containerPort: 8080
          resources:
            requests: { cpu: 100m, memory: 128Mi }
            limits: { memory: 256Mi }
          readinessProbe:
            httpGet: { path: /healthz, port: 8080 }
```

## Cosa può andare storto

- **Deployment degradato**: `readyReplicas` è inferiore a `replicas`. Il [Centro Operativo](app:/operations-center) lo segnala automaticamente.
- **Rollout bloccato**: la nuova versione non diventa mai ready (immagine errata, probe che fallisce, crash all'avvio). Con `maxUnavailable: 0` i vecchi Pod restano attivi, quindi il servizio continua, ma l'aggiornamento non avanza.
- **Pod in [CrashLoopBackOff](guide:crashloopbackoff) o [ImagePullBackOff](guide:imagepullbackoff)** dopo un cambio di immagine o di tag.
- **Selector incoerente**: se le etichette del template non corrispondono al selector, l'API rifiuta l'oggetto.
- **Pod [Pending](guide:pending)**: richieste di risorse troppo alte per i nodi disponibili.

## Come verificare

In Scarlet: apri il Deployment, controlla repliche pronte/desiderate e la scheda Eventi; la pagina [Operazioni → Rollout](app:/operations/rollout) mostra lo stato dell'aggiornamento in corso.

Da shell (alternativa per l'amministratore):

```bash
kubectl -n shop get deployment web
kubectl -n shop rollout status deployment/web
kubectl -n shop describe deployment web
kubectl -n shop get rs,pods -l app=web
```

## Come risolvere

1. Leggi gli eventi del Deployment e dei Pod più recenti: indicano quasi sempre la causa.
2. Se la nuova versione è difettosa, esegui un [rollback](guide:rollback) dalla pagina Rollout (equivalente: `kubectl -n shop rollout undo deployment/web`).
3. Se mancano risorse, riduci le richieste o aggiungi capacità al cluster; vedi [Pending](guide:pending).
4. Per cambiare il numero di copie usa [Operazioni → Scale](app:/operations/scale) (procedura: [Scalare un'applicazione](guide:proc-scalare)).
5. Correggi il manifest nella scheda YAML, validalo con il dry-run lato server, controlla il diff e applica: il Deployment avvierà un nuovo rollout.
