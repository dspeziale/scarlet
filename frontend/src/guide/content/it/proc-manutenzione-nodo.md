---
title: Manutenzione di un nodo
summary: Come svuotare un nodo in sicurezza con cordon e drain e rimetterlo in servizio con uncordon.
category: procedures
order: 110
keywords: manutenzione, cordon, drain, uncordon, eviction, poddisruptionbudget, nodo, patch, riavvio
related: node, alta-disponibilita, proc-verificare-nodo, daemonset, replica, scheduling
---

## Quando serve

Prima di qualsiasi intervento che rende un nodo indisponibile: aggiornamento del sistema operativo, riavvio, aggiornamento di kubelet, sostituzione hardware, spostamento della VM. Lo scopo è spostare i Pod su altri nodi in modo ordinato, invece di farli morire bruscamente.

## Prerequisiti

- Ruolo **Operator** o **Administrator**.
- Gli altri nodi hanno **capacità libera** sufficiente ad accogliere i Pod spostati (controlla [Cluster → Nodi](app:/cluster/nodes) e le request).
- Le applicazioni critiche hanno almeno 2 [repliche](guide:replica) e, idealmente, un PodDisruptionBudget (vedi [Alta disponibilità](guide:alta-disponibilita)).
- Sai quali Pod usano storage locale (`emptyDir`, volumi locali): i dati di un `emptyDir` vanno persi quando il Pod viene sfrattato.

## Procedura

1. **Verifica il nodo** come descritto in [Verificare un nodo](guide:proc-verificare-nodo) e annota quali Pod ospita.
2. **Cordon.** In [Operazioni → Manutenzione](app:/operations/maintenance) seleziona il nodo ed esegui **Cordon**. Il nodo diventa `SchedulingDisabled`: i Pod esistenti continuano a girare, ma non ne arrivano di nuovi.
3. **Drain.** Esegui **Drain** sullo stesso nodo. Scarlet:
   - sfratta i Pod tramite l'**Eviction API**, quindi rispetta i **PodDisruptionBudget**: se uno sfratto violerebbe un PDB viene rifiutato e ritentato;
   - **salta i Pod dei DaemonSet**, che per definizione devono restare su ogni nodo;
   - lascia ai controller (Deployment, StatefulSet, ReplicaSet) il compito di ricreare i Pod su altri nodi.
4. **Segui l'avanzamento.** Il drain termina quando sul nodo restano solo Pod di DaemonSet (e Pod statici). Se rimane bloccato, leggi il motivo indicato (di solito un PDB che non consente interruzioni).
5. **Controlla le applicazioni.** Nel [Centro Operativo](app:/operations-center) non devono comparire nuovi Pod `Pending` o Deployment degradati.
6. **Esegui la manutenzione** sul nodo (fuori da Scarlet, ad esempio via SSH): aggiornamenti, riavvio, ecc.
7. **Attendi che il nodo torni `Ready`** in [Cluster → Nodi](app:/cluster/nodes).
8. **Uncordon.** Esegui **Uncordon** in [Manutenzione](app:/operations/maintenance). Il nodo torna schedulabile.

Equivalenti da shell:

```bash
kubectl cordon worker-02
kubectl drain worker-02 --ignore-daemonsets --delete-emptydir-data --timeout=10m
# ... manutenzione ...
kubectl uncordon worker-02
kubectl get pdb -A
```

Attenzione: `--delete-emptydir-data` accetta la perdita dei dati `emptyDir`.

## Verifica

- Il nodo è `Ready` e non più `SchedulingDisabled`.
- Tutti i Deployment hanno repliche disponibili pari a quelle desiderate.
- Nessun Pod `Pending` nel Centro Operativo.
- I Pod dei DaemonSet sul nodo sono `Running`.

Nota: dopo l'uncordon Kubernetes **non ribilancia** automaticamente i Pod già spostati. Il nodo si riempirà con i nuovi Pod creati in seguito; se serve, un riavvio controllato da [Operazioni → Restart](app:/operations/restart) ridistribuisce i Pod di un Deployment.

## Se qualcosa va storto

- **Drain bloccato da un PDB**: il budget non consente interruzioni (ad esempio `minAvailable` uguale al numero di repliche, o repliche non tutte Ready). Aumenta temporaneamente le repliche, oppure correggi i Pod non Ready. Non cancellare il PDB senza averne valutato l'impatto.
- **Pod non gestiti da un controller**: un Pod "nudo" non viene ricreato altrove. Va ricreato manualmente o trasformato in Deployment.
- **Pod `Pending` dopo il drain**: capacità insufficiente sugli altri nodi, oppure vincoli (nodeSelector, affinity, PVC legati al nodo). Valuta di fare uncordon e rimandare la manutenzione.
- **Il nodo non torna `Ready`** dopo la manutenzione: segui [Nodo NotReady](guide:node-notready) e lascialo in cordon finché non è risolto.
