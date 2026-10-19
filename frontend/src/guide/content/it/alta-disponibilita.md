---
title: Alta disponibilità
summary: Progettare applicazioni che continuano a funzionare quando un Pod o un nodo si ferma.
category: reliability
order: 80
keywords: alta disponibilità, high availability, ha, poddisruptionbudget, pdb, disruption, anti-affinity, topology spread
related: replica, scheduling, node, proc-manutenzione-nodo, readiness-probe, cluster
---

## In parole semplici

**Alta disponibilità** significa che il servizio resta in piedi anche quando qualcosa si rompe o viene fermato: un Pod che crasha, un nodo che si spegne, una manutenzione programmata. Si ottiene con tre ingredienti:

1. **Più copie** dell'applicazione ([repliche](guide:replica)).
2. **Distribuite** su nodi diversi, così un guasto non le colpisce tutte.
3. **Protette** durante le operazioni pianificate, grazie al PodDisruptionBudget.

## Dettagli tecnici

**Interruzioni (disruption)**. Kubernetes distingue:
- *involontarie*: guasto hardware, kernel panic, nodo irraggiungibile, espulsione per mancanza di risorse;
- *volontarie*: drain di un nodo per manutenzione, eliminazione di un Pod, aggiornamento del cluster.

**PodDisruptionBudget (PDB)**. Definisce quante repliche di un gruppo di Pod (selezionati per label) devono restare disponibili durante le interruzioni **volontarie** che passano dalla Eviction API, come `kubectl drain` o la funzione drain di [Manutenzione](app:/operations/maintenance). Si usa `minAvailable` oppure `maxUnavailable` (numero o percentuale). Se un'espulsione violerebbe il budget, l'API risponde con errore 429 e il drain riprova. Il PDB **non** protegge dai guasti involontari né dall'eliminazione diretta di un Pod.

**Distribuzione**:
- `topologySpreadConstraints` distribuisce i Pod tra nodi (`kubernetes.io/hostname`) o zone (`topology.kubernetes.io/zone`).
- `podAntiAffinity` evita (in modo obbligatorio o preferito) che due repliche finiscano sullo stesso nodo.

**Lato cluster**: control plane con più nodi (almeno 3 per il quorum di etcd), worker sufficienti ad assorbire la perdita di un nodo, storage e ingress ridondati. Quando un nodo diventa NotReady, i suoi Pod vengono espulsi dopo circa 5 minuti (toleration predefinita `node.kubernetes.io/unreachable` di 300 secondi).

La pagina [Monitoraggio → Alta affidabilità](app:/monitoring/ha) aiuta a individuare workload con una sola replica, repliche concentrate su un nodo o senza PDB.

## Esempio

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: web-pdb
  namespace: shop
spec:
  minAvailable: 2
  selector:
    matchLabels:
      app: web
---
# Nel template del Deployment "web" (3 repliche)
spec:
  template:
    spec:
      topologySpreadConstraints:
        - maxSkew: 1
          topologyKey: kubernetes.io/hostname
          whenUnsatisfiable: DoNotSchedule
          labelSelector:
            matchLabels:
              app: web
```

Alternativa da shell:

```bash
kubectl -n shop get pdb
kubectl -n shop get pods -l app=web -o wide
```

## Cosa può andare storto

- **Drain bloccato**: un PDB con `minAvailable` uguale al numero di repliche (o `maxUnavailable: 0`) non permette nessuna espulsione.
- **PDB su workload con una sola replica**: la manutenzione non può procedere senza interruzione.
- **Tutte le repliche sullo stesso nodo**: la caduta del nodo ferma il servizio nonostante le repliche.
- **`DoNotSchedule` troppo rigido**: con pochi nodi i nuovi Pod restano in `Pending`.
- **Singoli punti di guasto** fuori dal cluster: un unico database, un unico storage NFS, un unico load balancer.

## Come verificare

- [Monitoraggio → Alta affidabilità](app:/monitoring/ha) per il quadro dei rischi.
- In [Pod](app:/k8s/pods) controlla la colonna nodo per vedere la distribuzione.
- Prima di una manutenzione, la pagina [Manutenzione](app:/operations/maintenance) mostra quali Pod verrebbero espulsi.

## Come risolvere

1. Porta i servizi importanti ad almeno 2-3 repliche.
2. Aggiungi `topologySpreadConstraints` o `podAntiAffinity` per distribuirle.
3. Crea un PDB con `maxUnavailable: 1` (o `minAvailable` inferiore al numero di repliche).
4. Esegui la manutenzione dei nodi seguendo [Manutenzione di un nodo](guide:proc-manutenzione-nodo).
