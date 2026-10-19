---
title: OOMKilled
summary: Il container ha superato il limite di memoria ed è stato terminato dal kernel.
category: troubleshooting
order: 40
keywords: oomkilled, out of memory, memoria, limit, exit code 137, oom killer, memory pressure
related: resource-limit, resource-request, crashloopbackoff, monitoring, troubleshooting, node-notready
---

## In parole semplici

Ogni container può avere un **limite di memoria**. Se il processo prova a usarne di più, il kernel Linux lo uccide immediatamente: è l'**OOM killer** (Out Of Memory). Kubernetes registra la terminazione con il motivo **OOMKilled** e codice di uscita **137**, poi riavvia il container. Se succede di continuo, il pod finisce in [CrashLoopBackOff](guide:crashloopbackoff).

Le cause tipiche sono due: il limite è troppo basso per il carico reale, oppure l'applicazione ha una perdita di memoria (memory leak) e cresce finché non viene uccisa.

## Dettagli tecnici

- `resources.limits.memory` viene tradotto in un limite del cgroup del container. Superarlo provoca un SIGKILL immediato, senza possibilità di chiusura ordinata.
- Lo stato è visibile in `status.containerStatuses[].lastState.terminated.reason: OOMKilled` con `exitCode: 137`.
- La CPU funziona diversamente: superare il limite di CPU provoca solo rallentamento (throttling), mai la terminazione.
- Esiste anche l'OOM **a livello di nodo**: se il nodo esaurisce la memoria, il kubelet sotto `MemoryPressure` sfratta (evict) i pod partendo da quelli con classe QoS più bassa (`BestEffort`, poi `Burstable` che superano le request, infine `Guaranteed`). In quel caso il pod risulta `Failed` con `reason: Evicted`.
- Runtime come la JVM o Node.js hanno heap configurabili: se l'heap massimo è vicino o superiore al limite del container, l'OOM è garantito. Ad esempio con Java è consigliato `-XX:MaxRAMPercentage=75`.

## Esempio

```bash
kubectl get pod report-7b5d4c9f8-h6t2r -n batch -o jsonpath='{.status.containerStatuses[0].lastState.terminated}'
# {"exitCode":137,"reason":"OOMKilled","startedAt":"...","finishedAt":"..."}

kubectl top pod report-7b5d4c9f8-h6t2r -n batch   # richiede metrics-server
```

```yaml
resources:
  requests:
    memory: "512Mi"
    cpu: "250m"
  limits:
    memory: "1Gi"
```

## Cosa può andare storto

- Si aumenta il limite senza aumentare la request: il pod viene schedulato su nodi che non hanno davvero quella memoria libera e il nodo va in pressione.
- Si alza il limite all'infinito per mascherare un memory leak: il problema si sposta sul nodo.
- Limite impostato in unità sbagliate (`1G` contro `1Gi`, oppure `512m` che significa 0,512 byte).
- Picchi di memoria all'avvio (cache, caricamento dati) superano il limite anche se l'uso a regime è basso.
- Senza metrics-server non si vede l'andamento della memoria: PKM mostra "Metriche avanzate non configurate".

## Come verificare

1. Nel [Centro Operativo](app:/operations-center) il problema compare come OOMKilled.
2. Apri il pod: in **Panoramica** guarda il motivo dell'ultima terminazione e il numero di riavvii.
3. In **Metriche** confronta l'uso di memoria con il limite; un andamento a dente di sega che tocca il limite indica OOM ripetuti.
4. In [Monitoraggio → Memoria](app:/monitoring/memory) verifica se il nodo è in pressione.
5. Negli **Eventi** del nodo cerca `SystemOOM` o `Evicted`.

## Come risolvere

1. Se l'uso di memoria è stabile ma vicino al limite: aumenta `limits.memory` (e coerentemente `requests.memory`) dal tab **YAML** del Deployment o con un nuovo deploy, validando con il dry-run.
2. Configura il runtime in base al limite (heap della JVM, `--max-old-space-size` di Node.js).
3. Se la memoria cresce senza fermarsi: è un memory leak; come mitigazione temporanea aumenta le [repliche](guide:replica) e segnala il problema agli sviluppatori.
4. Se il problema è a livello di nodo: riduci il carico, sposta i pod o aggiungi capacità (vedi [Resource request](guide:resource-request)).
5. Se è comparso dopo un rilascio, valuta un [rollback](guide:proc-rollback).
