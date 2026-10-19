---
title: Verificare lo stato del cluster
summary: Un controllo rapido e ripetibile della salute del cluster, da fare all'inizio del turno o dopo un intervento.
category: procedures
order: 40
keywords: verifica, salute, health, cluster, nodi, eventi, centro operativo, check
related: cluster, node, monitoring, proc-verificare-nodo, troubleshooting, node-notready
---

## Quando serve

- All'inizio del turno, come controllo di routine.
- Dopo un intervento (aggiornamento, manutenzione di un nodo, deploy importante).
- Quando qualcuno segnala "l'applicazione è lenta" o "non risponde" e vuoi capire se il problema è del cluster o della singola applicazione.

## Prerequisiti

- Scarlet collegato al cluster (badge **LIVE** visibile). Se vedi il banner **DEMO**, stai guardando dati di esempio.
- Ruolo almeno **Viewer**.

## Procedura

1. **Salute di Scarlet e delle integrazioni.** Apri [Monitoraggio → Health](app:/monitoring/health). Backend, database, Kubernetes e Podman dovrebbero essere **Healthy**. Se Kubernetes è Unhealthy, tutto ciò che vedi dopo potrebbe essere incompleto: risolvi prima la connessione ([Collegare Kubernetes](guide:proc-collegare-kubernetes)).

2. **Problemi già rilevati.** Apri il [Centro Operativo](app:/operations-center). Ordina per gravità: prima **CRITICAL** ed **ERROR**, poi WARNING. Per ogni voce leggi la risorsa coinvolta, il rischio e le azioni suggerite.

3. **Nodi.** In [Cluster → Nodi](app:/cluster/nodes) tutti i nodi devono essere **Ready**. Controlla anche:
   - nodi marcati **SchedulingDisabled** (cordon dimenticato dopo una manutenzione?);
   - condizioni di pressione: `MemoryPressure`, `DiskPressure`, `PIDPressure` devono essere `False`.

4. **Uso delle risorse.** In [Monitoraggio → CPU](app:/monitoring/cpu) e [Memoria](app:/monitoring/memory) cerca nodi stabilmente sopra l'80-90%. Se compare "Metriche avanzate non configurate", metrics-server non è disponibile: Scarlet non inventa i valori. In [Storage](app:/monitoring/storage) controlla lo spazio.

5. **Workload.** In [Applicazioni → Deployments](app:/k8s/deployments) confronta repliche desiderate e pronte (es. `3/3`). Un `2/3` persistente indica un problema. Fai lo stesso per StatefulSets e DaemonSets.

6. **Eventi recenti.** In [Cluster → Eventi](app:/cluster/events) filtra per tipo **Warning** e guarda gli ultimi 30-60 minuti. Eventi ripetuti (`BackOff`, `FailedScheduling`, `FailedMount`, `Unhealthy`) sono indizi preziosi.

7. **Storage.** In [Persistent Volume Claims](app:/k8s/persistentvolumeclaims) nessun PVC dovrebbe restare a lungo **Pending**.

8. **Alta affidabilità.** In [Monitoraggio → Alta affidabilità](app:/monitoring/ha) verifica che le applicazioni critiche abbiano più repliche distribuite su nodi diversi.

Alternativa da shell, per un amministratore:

```bash
kubectl get nodes -o wide
kubectl get pods -A --field-selector=status.phase!=Running,status.phase!=Succeeded
kubectl get events -A --field-selector type=Warning --sort-by=.lastTimestamp | tail -30
kubectl top nodes           # richiede metrics-server
kubectl get pvc -A | grep -v Bound
```

## Verifica

Il cluster si può considerare in salute quando:

- Health è tutto **Healthy** (o Degraded solo per componenti facoltativi come Prometheus);
- il Centro Operativo non ha voci CRITICAL o ERROR aperte;
- tutti i nodi sono Ready e schedulabili;
- i Deployment hanno repliche pronte uguali a quelle desiderate;
- non ci sono eventi Warning ripetuti negli ultimi minuti.

Annota l'esito, soprattutto se fai il controllo a inizio turno: ti servirà per capire **quando** è cambiato qualcosa.

## Se qualcosa va storto

- **Un nodo NotReady**: segui [Nodo NotReady](guide:node-notready) e [Verificare un nodo](guide:proc-verificare-nodo).
- **Pod in errore**: usa [Diagnosticare un Pod](guide:proc-diagnosticare-pod).
- **Molti problemi insieme**: probabilmente c'è una causa comune (un nodo, la rete, lo storage, un registry irraggiungibile). Non correggere i sintomi uno per uno: applica il [metodo di troubleshooting](guide:troubleshooting) e, se l'impatto è sugli utenti, la [gestione incidenti](guide:proc-gestione-incidenti).
