---
title: Resource limit
summary: Il tetto massimo di CPU e RAM che un container può usare.
category: reliability
order: 70
keywords: limits, resource limit, cpu, memoria, ram, throttling, oomkilled, cgroup
related: resource-request, oomkilled, monitoring, container, node
---

## In parole semplici

Il **limit** è il tetto massimo: il container non può usare più di quella quantità di CPU o di memoria. Serve a evitare che un'applicazione difettosa (per esempio con una perdita di memoria) consumi tutto il nodo e danneggi le altre.

Le conseguenze del superamento sono diverse:
- **CPU oltre il limit**: il container viene **rallentato** (throttling), ma continua a girare.
- **Memoria oltre il limit**: il container viene **ucciso** dal kernel ([OOMKilled](guide:oomkilled)) e riavviato.

## Dettagli tecnici

- Si imposta in `resources.limits`, con le stesse unità delle [request](guide:resource-request): `cpu: 1` o `500m`, `memory: 512Mi`.
- Il kubelet traduce i limit in impostazioni cgroup del container (su Oracle Linux 9 cgroup v2): `cpu.max` per la CPU e `memory.max` per la memoria.
- **CPU**: la quota è calcolata su periodi di 100 ms. Un container con `limits.cpu: 500m` può usare 50 ms di CPU ogni 100 ms; se li esaurisce aspetta il periodo successivo. Questo causa latenze anche quando il nodo ha CPU libera. Molte organizzazioni preferiscono impostare solo la request CPU e nessun limit.
- **Memoria**: se il container supera `memory.max`, l'OOM killer termina un processo del container; il container risulta `Terminated` con reason `OOMKilled` ed exit code 137.
- Diverso è l'**eviction**: quando l'intero nodo è sotto pressione di memoria, il kubelet espelle Pod interi (stato `Failed`, reason `Evicted`) anche se rispettano il proprio limit.
- La somma dei limit sui Pod di un nodo può superare la capacità del nodo (*overcommit*): è ammesso, ma aumenta il rischio di pressione di memoria.
- Per applicazioni Java, Node.js e simili, la memoria del runtime (heap) va configurata in modo coerente con il limit, lasciando margine per lo stack e la memoria nativa.

## Esempio

```yaml
containers:
  - name: worker
    image: registry.example.com/shop/worker:3.0.4
    env:
      - name: JAVA_TOOL_OPTIONS
        value: "-XX:MaxRAMPercentage=75"
    resources:
      requests:
        cpu: 500m
        memory: 768Mi
      limits:
        cpu: "2"
        memory: 1Gi
```

Alternativa da shell per verificare un OOMKilled:

```bash
kubectl -n shop get pod worker-6b8f9d7c4-l9zt2 \
  -o jsonpath='{.status.containerStatuses[0].lastState.terminated.reason}'
```

## Cosa può andare storto

- **Limit di memoria troppo basso**: OOMKilled ripetuti, che sfociano in [CrashLoopBackOff](guide:crashloopbackoff).
- **Limit CPU troppo basso**: tempi di risposta alti, timeout delle probe, riavvii causati dalla [liveness probe](guide:liveness-probe).
- **Nessun limit di memoria**: un leak può saturare il nodo e provocare l'espulsione di altri Pod.
- **Heap del runtime più grande del limit**: l'applicazione viene uccisa prima che il garbage collector intervenga.
- **LimitRange** del namespace che impone limit di default non adatti.

## Come verificare

- In [Monitoraggio → Memoria](app:/monitoring/memory) e [CPU](app:/monitoring/cpu) confronta l'uso con i limit (dati da metrics-server; la storia richiede Prometheus).
- Nel dettaglio del Pod la scheda **Diagnostica** segnala OOMKilled e riavvii; la scheda **Metriche** mostra il consumo attuale.
- Il [Centro Operativo](app:/operations-center) elenca i container OOMKilled.

## Come risolvere

1. Se il container va in OOMKilled, aumenta `limits.memory` (o riduci l'heap configurato) dopo aver verificato che non si tratti di un leak.
2. Se c'è throttling CPU, aumenta `limits.cpu` o rimuovilo mantenendo una request adeguata.
3. Mantieni un rapporto ragionevole tra request e limit di memoria (per servizi critici, uguali).
4. Modifica il manifest dalla scheda **YAML**, valida, controlla il diff e applica.
