---
title: Pod in Pending
summary: Il pod è stato creato ma non è ancora in esecuzione, di solito perché nessun nodo può ospitarlo.
category: troubleshooting
order: 50
keywords: pending, failedscheduling, scheduling, risorse insufficienti, taint, affinity, pvc pending, unschedulable
related: scheduling, resource-request, node, persistent-volume-claim, storage-class, troubleshooting
---

## In parole semplici

Un pod in **Pending** è stato accettato dal cluster ma non è ancora partito. Nella maggior parte dei casi lo [scheduler](guide:scheduling) non trova un nodo adatto: le risorse richieste sono troppe, i nodi disponibili hanno restrizioni (taint) che il pod non tollera, oppure il pod aspetta un volume che non è ancora disponibile. Più raramente il pod è già assegnato a un nodo ma sta ancora scaricando l'immagine.

Un breve Pending (qualche secondo) è normale. Un Pending che dura minuti è un problema da indagare.

## Dettagli tecnici

- Se `spec.nodeName` è vuoto, il pod non è stato schedulato: la condizione `PodScheduled` è `False` con `reason: Unschedulable` e c'è un evento `FailedScheduling`.
- Il messaggio di `FailedScheduling` riassume perché ogni nodo è stato scartato, ad esempio:
  `0/3 nodes are available: 1 node(s) had untolerated taint {node-role.kubernetes.io/control-plane: }, 2 Insufficient memory.`
- Cause principali:
  - **Insufficient cpu/memory**: la somma delle `requests` dei pod sul nodo più quelle del nuovo pod supera l'`allocatable` del nodo. Conta la request, non l'uso reale.
  - **Taint non tollerati**: nodi con `NoSchedule` (control plane, nodi dedicati, nodi in cordon con `node.kubernetes.io/unschedulable`).
  - **nodeSelector / affinity** che nessun nodo soddisfa, o anti-affinity troppo stretta.
  - **PVC non bound**: `pod has unbound immediate PersistentVolumeClaims`. Con `volumeBindingMode: WaitForFirstConsumer` il volume viene creato solo dopo la scelta del nodo.
  - **Quote**: una ResourceQuota impedisce la creazione del pod (in questo caso il pod spesso non viene creato affatto e l'errore è sul ReplicaSet).
- Se `nodeName` è valorizzato ma il pod è ancora Pending, il problema è sul nodo: pull dell'immagine in corso, mount del volume, init container in esecuzione.

## Esempio

```bash
kubectl get pod db-0 -n shop
# NAME   READY   STATUS    RESTARTS   AGE
# db-0   0/1     Pending   0          7m

kubectl describe pod db-0 -n shop | sed -n '/Events/,$p'
#  Warning  FailedScheduling  default-scheduler  0/3 nodes are available:
#  3 node(s) didn't find available persistent volumes to bind.

kubectl get pvc -n shop
kubectl describe nodes | grep -A8 "Allocated resources"
```

## Cosa può andare storto

- Le request sono state copiate da un altro ambiente e sono troppo alte per questo cluster.
- Tutti i nodi worker sono in cordon dopo una manutenzione e nessuno ha eseguito l'uncordon.
- La StorageClass non esiste, non ha un provisioner funzionante, o non c'è una StorageClass di default.
- Un DaemonSet o un altro carico ha consumato le risorse allocabili.
- Una regola di anti-affinity richiede più nodi di quelli disponibili (ad esempio 4 repliche con anti-affinity obbligatoria su 3 nodi).

## Come verificare

1. Nel [Centro Operativo](app:/operations-center) i pod Pending e i PVC Pending sono segnalati separatamente.
2. Apri il pod e leggi gli **Eventi**: il messaggio `FailedScheduling` dice quanti nodi sono stati scartati e perché.
3. Nella scheda **Diagnostica** PKM riassume la causa probabile.
4. Controlla i nodi in [Cluster → Nodi](app:/cluster/nodes): stato, schedulabilità (cordon) e risorse allocate.
5. Se c'è un volume, verifica il PVC in [Storage → Persistent Volume Claims](app:/k8s/persistentvolumeclaims) e la [StorageClass](app:/k8s/storageclasses).

## Come risolvere

1. **Risorse insufficienti**: riduci le `requests` se sovradimensionate, riduci le repliche di carichi meno importanti, oppure aggiungi nodi.
2. **Nodi in cordon**: se la manutenzione è finita, esegui l'uncordon da [Operazioni → Manutenzione](app:/operations/maintenance).
3. **Taint/affinity**: correggi `nodeSelector`, `affinity` o aggiungi la `toleration` corretta nel tab **YAML**, validando con il dry-run.
4. **PVC Pending**: verifica la StorageClass e il provisioner; vedi [Persistent Volume Claim](guide:persistent-volume-claim).
5. Dopo la correzione lo scheduler riprova automaticamente: non serve ricreare il pod.
