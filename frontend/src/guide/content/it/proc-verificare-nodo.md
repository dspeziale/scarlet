---
title: Verificare un nodo
summary: Come controllare lo stato di salute di un nodo e capire se può ospitare carichi di lavoro.
category: procedures
order: 90
keywords: nodo, node, notready, condizioni, pressure, kubelet, capacità, verifica
related: node, node-notready, proc-manutenzione-nodo, monitoring, scheduling, pending
---

## Quando serve

- Il [Centro Operativo](app:/operations-center) segnala un nodo `NotReady`.
- Più Pod dello stesso nodo falliscono, vengono sfrattati (evicted) o restano `Pending`.
- Prima e dopo una manutenzione, per confermare che il nodo sia sano.
- Durante un controllo periodico della capacità del cluster.

## Prerequisiti

- Qualsiasi ruolo può consultare i nodi; per cordon, drain e uncordon serve almeno **Operator**.
- Per CPU e memoria in tempo reale serve metrics-server installato nel cluster.
- Per azioni sul sistema operativo del nodo (riavvio di kubelet, controllo disco) serve accesso SSH al nodo: PKM non esegue comandi sui nodi.

## Procedura

1. **Apri l'elenco dei nodi.** Vai su [Cluster → Nodi](app:/cluster/nodes). Per ogni nodo controlla stato (`Ready`/`NotReady`), ruoli, versione di kubelet, se è schedulabile (un nodo in cordon appare come `SchedulingDisabled`) ed età.
2. **Apri il dettaglio del nodo.** Nella scheda **Panoramica** controlla le **condizioni**:
   - `Ready=True`: il kubelet risponde ed è sano.
   - `MemoryPressure`, `DiskPressure`, `PIDPressure` devono essere `False`. Se una è `True`, il kubelet comincia a sfrattare Pod.
   - `NetworkUnavailable` deve essere `False`.
   - `Ready=Unknown` significa che il control plane non riceve più notizie dal kubelet (di default dopo circa 40 secondi).
3. **Controlla capacità e allocazione.** Confronta `capacity` e `allocatable` con la somma delle request dei Pod presenti. Un nodo con request al 100% non accetta nuovi Pod anche se l'uso reale è basso.
4. **Controlla le metriche.** Nella scheda **Metriche** o in [Monitoraggio → CPU](app:/monitoring/cpu) e [Memoria](app:/monitoring/memory) verifica l'uso reale. Uso stabilmente sopra l'85-90% è un segnale di rischio.
5. **Leggi gli eventi del nodo.** Nella scheda **Eventi** cerca `NodeNotReady`, `NodeHasDiskPressure`, `EvictionThresholdMet`, `Rebooted`.
6. **Guarda i Pod ospitati.** Nella scheda **Relazioni** controlla quali Pod girano sul nodo e se ci sono Pod in stato anomalo.
7. **Controlla taint.** Nello YAML del nodo verifica `spec.taints`: un taint `NoSchedule` impedisce lo scheduling ai Pod senza toleration corrispondente. Il taint `node.kubernetes.io/unreachable` viene aggiunto automaticamente ai nodi irraggiungibili.

Equivalenti da shell:

```bash
kubectl get nodes -o wide
kubectl describe node worker-02
kubectl top node worker-02
kubectl get pods -A --field-selector spec.nodeName=worker-02
# sul nodo, via SSH
systemctl status kubelet
journalctl -u kubelet --since "30 min ago"
df -h /var/lib
```

## Verifica

- Il nodo è `Ready` e tutte le condizioni di pressione sono `False`.
- Il nodo non è in `SchedulingDisabled`, a meno che sia voluto per manutenzione.
- Uso di CPU e memoria con margine sufficiente.
- Nessun evento `Warning` recente sul nodo.
- La pagina [Health](app:/monitoring/health) mostra Kubernetes come Healthy.

## Se qualcosa va storto

- **Nodo `NotReady`**: verifica via SSH che il nodo sia acceso e che `kubelet` e il container runtime siano attivi; controlla rete e certificati. Dettagli in [Nodo NotReady](guide:node-notready).
- **`DiskPressure`**: libera spazio (immagini inutilizzate, log) sul nodo; il kubelet tenta da solo la garbage collection delle immagini.
- **`MemoryPressure`**: alcuni Pod usano più memoria di quanto richiesto. Rivedi [request](guide:resource-request) e [limit](guide:resource-limit).
- **Il nodo deve essere riparato**: mettilo in manutenzione con cordon e drain, vedi [Manutenzione di un nodo](guide:proc-manutenzione-nodo).
- **Metriche non disponibili**: compare "Metriche avanzate non configurate". Installa metrics-server o configura Prometheus in Impostazioni.
