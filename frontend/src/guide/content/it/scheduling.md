---
title: Scheduling
summary: Come Kubernetes sceglie il nodo su cui far girare ogni pod, e perché a volte non ne trova nessuno.
category: concepts
order: 60
keywords: scheduling, scheduler, affinity, taint, toleration, nodeselector, failedscheduling, topology spread
related: node, pod, pending, resource-request, alta-disponibilita, proc-manutenzione-nodo
---

## In parole semplici

Quando nasce un nuovo pod, qualcuno deve decidere su quale nodo metterlo: è il compito dello **scheduler**. Lo scheduler scarta i nodi che non vanno bene (poca CPU o memoria libera, regole che lo vietano) e tra quelli rimasti sceglie il migliore.

Se nessun nodo va bene, il pod resta in stato [Pending](guide:pending) e negli eventi compare un messaggio `FailedScheduling` che spiega il perché. Leggere bene quel messaggio risolve la maggior parte dei casi.

## Dettagli tecnici

Lo scheduler (`kube-scheduler`) lavora in due fasi:

1. **Filtering**: elimina i nodi non idonei. Controlli principali:
   - **Risorse**: la somma delle [request](guide:resource-request) dei pod già sul nodo più quelle del nuovo pod deve stare dentro `allocatable`. Conta la request, non l'uso reale.
   - **nodeSelector** e **nodeAffinity** (`requiredDuringSchedulingIgnoredDuringExecution`): il nodo deve avere certe label.
   - **Taint e toleration**: un nodo con taint `NoSchedule` accetta solo pod con la toleration corrispondente. I nodi del control plane hanno di solito `node-role.kubernetes.io/control-plane:NoSchedule`.
   - **Nodo non schedulabile** (cordon) o non pronto.
   - **Volumi**: un PVC con volume zonale o locale vincola il pod ai nodi che possono montarlo.
   - **podAntiAffinity obbligatoria**: ad esempio "mai due repliche sullo stesso nodo".
2. **Scoring**: ordina i nodi idonei (bilanciamento delle risorse, affinità preferite, `topologySpreadConstraints`, immagine già presente) e sceglie il punteggio più alto.

Il risultato è scritto in `spec.nodeName`. Una volta assegnato, un pod **non viene più spostato** dallo scheduler, anche se le regole cambiano ("IgnoredDuringExecution"). Viene spostato solo se viene sfrattato o cancellato e ricreato.

Con le **PriorityClass**, un pod ad alta priorità può causare la **preemption** (sfratto) di pod a priorità più bassa per fare spazio.

## Esempio

Distribuire le repliche su nodi diversi ed evitare i nodi dedicati:

```yaml
spec:
  topologySpreadConstraints:
    - maxSkew: 1
      topologyKey: kubernetes.io/hostname
      whenUnsatisfiable: ScheduleAnyway
      labelSelector:
        matchLabels:
          app: ordini
  nodeSelector:
    kubernetes.io/os: linux
  tolerations:
    - key: dedicato
      operator: Equal
      value: batch
      effect: NoSchedule
```

Tipico messaggio di errore:

```text
0/4 nodes are available: 1 node(s) had untolerated taint {node-role.kubernetes.io/control-plane: },
3 Insufficient memory. preemption: 0/4 nodes are available
```

```bash
# Alternativa da shell
kubectl get events -n ordini --field-selector reason=FailedScheduling
kubectl describe node worker-01 | grep -A8 "Allocated resources"
kubectl get nodes -o custom-columns=NAME:.metadata.name,TAINTS:.spec.taints
```

## Cosa può andare storto

- **Insufficient cpu / memory**: le request sono troppo alte rispetto allo spazio libero (non all'uso reale).
- **Taint non tollerati**: nodi riservati o in stato not-ready.
- **Affinity o nodeSelector impossibili**: label che nessun nodo ha (spesso un errore di battitura).
- **Volume node affinity conflict**: il PV è in una zona o su un nodo diverso.
- **Anti-affinity obbligatoria** con più repliche che nodi.
- Dopo un drain, pod che non trovano posto altrove.

## Come verificare

- Dettaglio del pod Pending, scheda **Eventi**: il messaggio `FailedScheduling` elenca i motivi per ogni gruppo di nodi.
- [Cluster → Nodi](app:/cluster/nodes): stato, taint, schedulabilità, risorse allocate.
- [Monitoraggio → Alta affidabilità](app:/monitoring/ha) per vedere come sono distribuite le repliche.

## Come risolvere

- Risorse insufficienti: riduci le request se sovradimensionate, libera capacità o aggiungi nodi.
- Taint: aggiungi la toleration solo se il pod deve davvero girare su quei nodi; se il nodo è in cordon dopo una manutenzione, esegui l'uncordon da [Operazioni → Manutenzione](app:/operations/maintenance).
- Affinity/nodeSelector: correggi le label nel YAML (scheda **YAML**, con dry-run e diff prima di applicare).
- Anti-affinity: passa da `required` a `preferred` oppure usa `topologySpreadConstraints` con `ScheduleAnyway`.
