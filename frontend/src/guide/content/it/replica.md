---
title: Repliche
summary: Più copie identiche dello stesso Pod per reggere il carico e sopravvivere ai guasti.
category: reliability
order: 10
keywords: repliche, replicas, scale, scalare, hpa, ridondanza
related: deployment, replicaset, statefulset, alta-disponibilita, proc-scalare
---

## In parole semplici

Una **replica** è una copia identica di un Pod. Se un'applicazione gira con tre repliche, Kubernetes mantiene sempre tre Pod uguali in esecuzione: se uno si ferma, il controller ne crea un altro. Più repliche significano più capacità di servire richieste e meno rischio che un singolo guasto blocchi il servizio.

Pensa a uno sportello con tre impiegati invece di uno: se uno va in pausa, gli altri continuano a servire.

## Dettagli tecnici

- Il numero desiderato si trova nel campo `spec.replicas` di Deployment, StatefulSet e ReplicaSet. Il valore reale è in `status.replicas`, `status.readyReplicas` e `status.availableReplicas`.
- Il **ReplicaSet** (gestito da un Deployment) confronta continuamente lo stato desiderato con quello reale e crea o elimina Pod per farli coincidere (riconciliazione).
- Le repliche di un Deployment sono **intercambiabili**: nomi casuali, nessuna identità stabile. Le repliche di uno StatefulSet hanno invece nome e storage stabili (`db-0`, `db-1`, ...).
- Il **Service** distribuisce il traffico solo tra le repliche *Ready* (vedi [Readiness probe](guide:readiness-probe)).
- Lo scaling può essere manuale (`spec.replicas`) oppure automatico con un **HorizontalPodAutoscaler** (HPA), che richiede metrics-server. Se un HPA gestisce il workload, una modifica manuale delle repliche verrà sovrascritta.
- Un DaemonSet non ha `replicas`: crea un Pod per ogni nodo idoneo.

Più repliche non bastano da sole all'alta disponibilità: se finiscono tutte sullo stesso nodo, la caduta del nodo le ferma tutte. Servono regole di distribuzione (vedi [Alta disponibilità](guide:alta-disponibilita)).

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
  template:
    metadata:
      labels:
        app: web
    spec:
      containers:
        - name: web
          image: registry.example.com/shop/web:1.4.2
```

Alternativa da shell (per amministratori):

```bash
kubectl -n shop scale deployment/web --replicas=5
kubectl -n shop get deployment web
```

## Cosa può andare storto

- **Repliche non pronte**: `READY 1/3` indica Pod in `Pending`, `CrashLoopBackOff` o con readiness probe fallita.
- **Risorse insufficienti**: aumentando le repliche, i nuovi Pod restano `Pending` se nessun nodo ha CPU/RAM richieste disponibili.
- **Scaling annullato**: un HPA o una pipeline GitOps riportano il valore a quello configurato.
- **Applicazione non progettata per più copie**: sessioni in memoria, job schedulati interni o file scritti localmente possono creare comportamenti incoerenti.
- **Una sola replica**: qualsiasi riavvio, aggiornamento o manutenzione del nodo causa un'interruzione.

## Come verificare

- In [Deployments](app:/k8s/deployments) la colonna delle repliche mostra pronte/desiderate; la scheda **Panoramica** del dettaglio riporta lo stato e la scheda **Relazioni** i Pod collegati.
- In [Pod](app:/k8s/pods) filtra per namespace e controlla su quali nodi girano le repliche.
- Il [Centro Operativo](app:/operations-center) segnala i deployment degradati.

```bash
kubectl -n shop get deploy web -o wide
kubectl -n shop get pods -l app=web -o wide
kubectl -n shop get hpa
```

## Come risolvere

1. Se le repliche pronte sono meno di quelle desiderate, apri i Pod non pronti e segui [Troubleshooting](guide:troubleshooting) (scheda **Diagnostica** ed **Eventi**).
2. Per cambiare il numero di repliche usa [Operazioni → Scale](app:/operations/scale) (vedi [Scalare un'applicazione](guide:proc-scalare)).
3. Se c'è un HPA, modifica `minReplicas`/`maxReplicas` invece di `replicas`.
4. Per i servizi importanti usa almeno 2-3 repliche e distribuiscile su nodi diversi.
