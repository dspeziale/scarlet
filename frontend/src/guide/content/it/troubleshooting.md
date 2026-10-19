---
title: Metodo di troubleshooting
summary: Un metodo ripetibile per capire e risolvere i problemi di pod, nodi e applicazioni senza andare a tentativi.
category: troubleshooting
order: 10
keywords: troubleshooting, diagnosi, problemi, errori, centro operativo, eventi, log, metodo
related: crashloopbackoff, imagepullbackoff, oomkilled, pending, node-notready, proc-diagnosticare-pod, proc-gestione-incidenti
---

## In parole semplici

Quando qualcosa non funziona, la tentazione è riavviare subito tutto. Spesso il problema sparisce per qualche minuto e poi ritorna, e nel frattempo si sono persi gli indizi. Il troubleshooting efficace segue invece un metodo: **Capire → Diagnosticare → Decidere → Agire → Verificare**. Prima si raccolgono i fatti (stato, eventi, log), poi si formula un'ipotesi, si sceglie l'azione con il rischio più basso, la si esegue e si controlla che il problema sia davvero risolto.

PKM è costruito attorno a questo metodo: il [Centro Operativo](app:/operations-center) rileva automaticamente i problemi più comuni, ogni risorsa ha una scheda **Diagnostica**, e le azioni (restart, rollback, scale) sono a portata di clic, ma solo dopo aver capito cosa succede.

## Dettagli tecnici

Un problema in Kubernetes si manifesta quasi sempre in uno di questi livelli:

| Livello | Dove guardare | Segnali tipici |
|---|---|---|
| Pod / container | stato del pod, `status.containerStatuses` | CrashLoopBackOff, ImagePullBackOff, OOMKilled, CreateContainerConfigError |
| Scheduling | eventi del pod (`FailedScheduling`) | Pending |
| Nodo | condizioni del nodo (`Ready`, `MemoryPressure`, `DiskPressure`, `PIDPressure`) | NotReady, evictions |
| Rete | Service, Endpoints, Ingress, DNS | Endpoints vuoti, 502/503 dall'Ingress |
| Storage | PVC, PV, StorageClass | PVC Pending, mount falliti (`FailedMount`) |
| Configurazione | ConfigMap, Secret, variabili | chiavi mancanti, valori errati |

Le fonti di informazione principali sono tre:

- **Stato**: la fase del pod (`Pending`, `Running`, `Succeeded`, `Failed`, `Unknown`) e, più importante, lo stato di ogni container (`waiting.reason`, `terminated.reason`, `exitCode`, `restartCount`).
- **Eventi**: messaggi brevi generati dai controller e dal kubelet. Durano per default circa un'ora, quindi vanno letti presto.
- **Log**: l'output del processo. Per un container che si riavvia, i log utili sono spesso quelli dell'istanza **precedente** (`--previous`).

Il Centro Operativo assegna una severità (CRITICAL, ERROR, WARNING, INFO), indica la risorsa coinvolta, il rischio e le azioni suggerite. Le metriche di CPU e memoria richiedono metrics-server: se non è installato, PKM mostra "Metriche avanzate non configurate" e non inventa valori.

## Esempio

Equivalente da shell del percorso che PKM segue nella scheda Diagnostica:

```bash
kubectl get pods -n shop -o wide
kubectl describe pod web-7d9f8c6b5-x2k4q -n shop      # stato ed eventi
kubectl logs web-7d9f8c6b5-x2k4q -n shop --previous   # log dell'istanza precedente
kubectl get events -n shop --sort-by=.lastTimestamp
kubectl top pod -n shop                                # richiede metrics-server
```

## Cosa può andare storto

- **Agire prima di capire**: un riavvio cancella lo stato e i log del container in errore.
- **Guardare solo i log**: se il container non parte mai (immagine non trovata, Secret mancante), i log sono vuoti. La causa è negli eventi.
- **Fermarsi al sintomo**: un 502 dall'Ingress può dipendere da una readiness probe sbagliata, non dall'Ingress.
- **Eventi scaduti**: dopo circa un'ora gli eventi spariscono; annota subito ciò che vedi.
- **Cambiare più cose insieme**: se il problema si risolve non saprai quale modifica ha funzionato.

## Come verificare

1. Apri il [Centro Operativo](app:/operations-center) e ordina per severità.
2. Apri la risorsa coinvolta e consulta in ordine: **Panoramica**, **Eventi**, **Log**, **Metriche**, **Diagnostica**.
3. Controlla gli eventi del cluster in [Cluster → Eventi](app:/cluster/events) per vedere se il problema è isolato o diffuso.
4. Verifica lo stato dei nodi in [Cluster → Nodi](app:/cluster/nodes).

## Come risolvere

1. **Capire**: descrivi il sintomo in una frase ("3 pod su 3 del deployment `web` in CrashLoopBackOff dalle 10:20").
2. **Diagnosticare**: identifica il livello (pod, nodo, rete, storage, config) e consulta l'articolo specifico, ad esempio [CrashLoopBackOff](guide:crashloopbackoff) o [Pending](guide:pending).
3. **Decidere**: scegli l'azione meno invasiva. Se il problema è iniziato con un rilascio, il [rollback](guide:proc-rollback) è spesso la scelta più sicura.
4. **Agire**: esegui una sola modifica alla volta dalle pagine Operazioni. Ogni azione viene registrata nell'Audit Log.
5. **Verificare**: controlla che i pod siano `Running` e `Ready`, che il conteggio dei riavvii sia stabile e che il problema sia sparito dal Centro Operativo. Segna il problema come gestito nel Notification Center.

Per incidenti che coinvolgono più servizi, segui la procedura [Gestione incidenti](guide:proc-gestione-incidenti).
