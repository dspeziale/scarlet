---
title: Namespace
summary: Uno spazio logico che separa le risorse del cluster per team, ambiente o applicazione.
category: concepts
order: 30
keywords: namespace, isolamento, resourcequota, limitrange, rbac, terminating
related: cluster, pod, resource-request, resource-limit, networking, secret
---

## In parole semplici

Un namespace è come una cartella dentro il cluster. Serve a tenere separate le risorse di applicazioni, team o ambienti diversi: ad esempio `produzione`, `collaudo`, `monitoring`. Due Deployment possono avere lo stesso nome se stanno in namespace diversi.

In Scarlet quasi tutte le liste hanno un filtro per namespace: impostarlo correttamente è il primo passo per non confondersi (e per non agire sulla risorsa sbagliata).

## Dettagli tecnici

- Le risorse **namespaced** (Pod, Deployment, Service, ConfigMap, Secret, PVC, Role...) appartengono a un solo namespace. Quelle **cluster-scoped** (Node, PersistentVolume, StorageClass, ClusterRole, Namespace stesso) no.
- Namespace di sistema: `default`, `kube-system` (componenti del cluster), `kube-public`, `kube-node-lease` (heartbeat dei nodi). Non distribuire applicazioni in `kube-system`.
- **RBAC**: un Role con RoleBinding concede permessi solo dentro un namespace; un ClusterRole può essere vincolato a un namespace con un RoleBinding.
- **ResourceQuota**: limita il totale di CPU, memoria, numero di oggetti in un namespace. Se esiste una quota su CPU/memoria, ogni pod deve dichiarare request e limit, altrimenti la creazione viene rifiutata.
- **LimitRange**: imposta valori di default e minimi/massimi per request e limit dei container.
- **DNS**: un Service è raggiungibile come `<service>.<namespace>.svc.cluster.local`; dentro lo stesso namespace basta `<service>`.
- Il namespace **non è un confine di rete**: senza NetworkPolicy i pod di namespace diversi si parlano liberamente.
- Cancellare un namespace cancella **tutto** ciò che contiene. Il namespace resta in stato `Terminating` finché tutti gli oggetti e i loro finalizer non sono rimossi.

## Esempio

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: collaudo
  labels:
    ambiente: collaudo
---
apiVersion: v1
kind: ResourceQuota
metadata:
  name: quota-collaudo
  namespace: collaudo
spec:
  hard:
    requests.cpu: "4"
    requests.memory: 8Gi
    limits.memory: 16Gi
    pods: "40"
```

```bash
# Alternativa da shell
kubectl get namespaces
kubectl get all -n collaudo
kubectl describe resourcequota -n collaudo
```

## Cosa può andare storto

- **Namespace sbagliato**: la risorsa "non esiste" solo perché il filtro punta altrove.
- **Quota superata**: errore `exceeded quota` alla creazione dei pod; il Deployment risulta degradato ma i pod non compaiono nemmeno (l'errore è negli eventi del ReplicaSet).
- **Pod rifiutato per request mancanti** quando c'è una ResourceQuota su CPU/memoria.
- **Namespace bloccato in Terminating**: qualche oggetto ha un finalizer che non viene rimosso (spesso un controller non più installato).
- **Cancellazione accidentale** di un namespace: perdita di tutte le risorse, e dei dati se i PV hanno policy Delete.

## Come verificare

- [Cluster → Namespace](app:/cluster/namespaces): elenco, stato, numero di risorse, quote.
- Dettaglio del namespace: **Eventi** e **Relazioni** mostrano cosa contiene.
- [Eventi del cluster](app:/cluster/events) filtrati per namespace, cercando `FailedCreate` o `exceeded quota`.

## Come risolvere

- Quota superata: riduci repliche o request, oppure chiedi all'amministratore di alzare la quota.
- Request mancanti: aggiungi `resources.requests` e `resources.limits` ai container (vedi [Resource request](guide:resource-request)) o chiedi un LimitRange con valori di default.
- Namespace in Terminating: individua gli oggetti rimasti (`kubectl api-resources --verbs=list --namespaced -o name | xargs -n1 kubectl get -n <ns> --ignore-not-found`) e risolvi il controller responsabile del finalizer. Rimuovere i finalizer a mano è l'ultima risorsa.
- Prima di cancellare un namespace, esporta i manifest da [Operazioni → Backup](app:/operations/backup).
