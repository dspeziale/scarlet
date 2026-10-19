---
title: Node
summary: Una macchina del cluster che esegue i pod tramite kubelet e il runtime dei container.
category: concepts
order: 20
keywords: nodo, node, kubelet, condizioni, ready, cordon, taint, capacità, allocatable
related: cluster, pod, scheduling, node-notready, proc-verificare-nodo, proc-manutenzione-nodo
---

## In parole semplici

Un nodo è una macchina (fisica o virtuale) che fa parte del cluster e su cui girano i pod. Se i pod sono gli inquilini, i nodi sono gli appartamenti: hanno una certa quantità di CPU, memoria e disco, e Kubernetes li riempie rispettando questi limiti.

Un nodo sano è **Ready**: comunica regolarmente con il control plane e può ricevere nuovi pod. Un nodo **NotReady** è un campanello d'allarme: i suoi pod potrebbero non funzionare e, dopo un po', verranno spostati altrove.

## Dettagli tecnici

Su ogni nodo girano `kubelet` (l'agente che avvia i container e riporta lo stato), il runtime dei container (containerd o CRI-O), `kube-proxy` e il plugin di rete CNI.

Lo `status` di un nodo contiene:

- **Conditions**: `Ready` (True/False/Unknown), `MemoryPressure`, `DiskPressure`, `PIDPressure`, `NetworkUnavailable`. `Ready=Unknown` significa che il kubelet non invia heartbeat da oltre `node-monitor-grace-period` (40 secondi di default).
- **Capacity** e **Allocatable**: risorse totali e quelle effettivamente disponibili per i pod (capacità meno le riserve di sistema). Lo scheduler ragiona su Allocatable e sulla somma delle [request](guide:resource-request), non sull'uso reale.
- **nodeInfo**: versione kubelet, sistema operativo, runtime.

Quando un nodo diventa NotReady/Unknown, il controller aggiunge i taint `node.kubernetes.io/not-ready` o `node.kubernetes.io/unreachable` con effetto `NoExecute`; i pod li tollerano per 300 secondi di default, poi vengono sfrattati e ricreati altrove (se gestiti da un controller).

**Cordon** imposta `spec.unschedulable: true`: nessun nuovo pod, quelli esistenti restano. **Drain** fa cordon e poi sfratta i pod con l'Eviction API. Vedi [Manutenzione del nodo](guide:proc-manutenzione-nodo).

## Esempio

```bash
# Alternativa da shell
kubectl get nodes -o wide
kubectl describe node worker-02
kubectl top node worker-02          # richiede metrics-server
kubectl get pods -A -o wide --field-selector spec.nodeName=worker-02
```

Estratto dello stato di un nodo:

```yaml
status:
  allocatable:
    cpu: "3800m"
    memory: 15Gi
    pods: "110"
  conditions:
    - type: Ready
      status: "True"
    - type: DiskPressure
      status: "False"
```

## Cosa può andare storto

- **NotReady / Unknown**: kubelet fermo, rete interrotta, nodo spento. Vedi [Node NotReady](guide:node-notready).
- **DiskPressure**: disco quasi pieno; il kubelet elimina immagini inutilizzate e può sfrattare pod.
- **MemoryPressure**: memoria scarsa; pod sfrattati, a partire da quelli BestEffort.
- **Nodo pieno di request**: nuovi pod restano [Pending](guide:pending) anche se l'uso reale è basso.
- **Nodo lasciato in cordon** dopo una manutenzione: capacità persa senza accorgersene.

## Come verificare

- [Cluster → Nodi](app:/cluster/nodes): stato, ruoli, versione, condizioni, se è schedulabile.
- Dettaglio del nodo: schede **Eventi**, **Metriche** (CPU/RAM da metrics-server), **Diagnostica**.
- [Monitoraggio → CPU](app:/monitoring/cpu) e [Memoria](app:/monitoring/memory) per confrontare i nodi.
- Procedura: [Verificare un nodo](guide:proc-verificare-nodo).

## Come risolvere

- NotReady: segui [Node NotReady](guide:node-notready); sull'host controlla `systemctl status kubelet` e `journalctl -u kubelet`.
- DiskPressure: libera spazio (log, immagini non usate con `crictl rmi --prune`), poi verifica che la condizione torni False.
- Capacità insufficiente: aggiungi nodi o riduci le request sovradimensionate.
- Manutenzione: usa [Operazioni → Manutenzione](app:/operations/maintenance) per cordon, drain e uncordon; non dimenticare l'uncordon finale.
