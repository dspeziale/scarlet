---
title: Scalare un'applicazione
summary: Aumenta o riduci il numero di repliche di un Deployment o StatefulSet in modo controllato.
category: procedures
order: 60
keywords: scale, scalare, repliche, replicas, deployment, statefulset, capacità, hpa
related: replica, deployment, statefulset, resource-request, alta-disponibilita, pending
---

## Quando serve

- Aumentare le repliche per reggere più carico o per avere ridondanza (almeno 2 per i servizi importanti).
- Ridurle per liberare risorse, ad esempio in ambienti di test.
- Portarle temporaneamente a `0` per fermare un'applicazione senza cancellarla (ad esempio prima di un intervento sul database che usa).

## Prerequisiti

- Ruolo **Operator** o **Administrator**.
- Capacità disponibile nel cluster: ogni nuova replica richiede le sue **request** di CPU e memoria. Controlla [Monitoraggio → CPU](app:/monitoring/cpu) e [Memoria](app:/monitoring/memory).
- Sapere se il workload ha un **HorizontalPodAutoscaler** (HPA): in quel caso l'HPA ricalcola le repliche e annullerà la tua modifica manuale. Bisogna agire sui valori minimo/massimo dell'HPA.

## Procedura

1. Apri [Operazioni → Scale](app:/operations/scale) (oppure il pulsante Scale nella pagina del Deployment o StatefulSet).
2. Seleziona namespace e workload. Il valore attuale di repliche desiderate e pronte è mostrato accanto.
3. Inserisci il nuovo numero di repliche. Procedi per gradi su cambi grandi (es. da 2 a 4, poi a 8) per non saturare nodi, database o servizi a valle.
4. Conferma. L'operazione è registrata nell'Audit Log.
5. Ricorda che lo scale fatto qui modifica il cluster, ma non il manifest nel tuo repository: se usi GitOps o pipeline, aggiorna anche lì `spec.replicas`, altrimenti il prossimo deploy riporterà il valore precedente.

Note sui tipi di workload:

- **Deployment**: le repliche sono intercambiabili, scale-up e scale-down sono immediati.
- **StatefulSet**: i Pod vengono creati in ordine (`nome-0`, `nome-1`, ...) e rimossi in ordine inverso. Ridurre le repliche **non** cancella i PVC dei Pod rimossi. Per database in cluster verifica prima che l'applicazione supporti la nuova dimensione.
- **DaemonSet**: non si scala; ha un Pod per ogni nodo idoneo.

Equivalente da shell:

```bash
kubectl -n produzione scale deployment/ordini-api --replicas=4
kubectl -n produzione rollout status deployment/ordini-api
kubectl -n produzione get hpa
```

## Verifica

- Nella pagina del workload le repliche pronte raggiungono il valore desiderato (es. `4/4`).
- I nuovi Pod sono **Running** e **Ready**, possibilmente su nodi diversi ([Alta affidabilità](app:/monitoring/ha)).
- In [Endpoints](app:/k8s/endpoints) il Service elenca il nuovo numero di indirizzi.
- Dopo qualche minuto, l'uso di CPU e memoria per Pod scende come previsto (se metrics-server è disponibile).

## Se qualcosa va storto

- **Nuovi Pod in Pending**: non c'è spazio sui nodi per le request richieste, oppure vincoli di affinità/taint lo impediscono. Leggi gli eventi `FailedScheduling` e vedi [Pending](guide:pending). Riduci le repliche o aggiungi capacità.
- **Le repliche tornano al valore precedente**: c'è un HPA o un sistema GitOps che riconcilia lo stato.
- **Scale-down e utenti con errori**: le richieste in corso vengono interrotte se l'applicazione non gestisce `SIGTERM`; configura un arresto ordinato e una readiness probe.
- **Pod che vanno in OOMKilled dopo lo scale-down**: le repliche rimaste ricevono più carico; vedi [OOMKilled](guide:oomkilled).
