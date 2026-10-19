---
title: CrashLoopBackOff
summary: Il container parte, termina subito e Kubernetes lo riavvia con attese sempre più lunghe.
category: troubleshooting
order: 20
keywords: crashloopbackoff, crash, riavvii, restart, back-off, exit code, log previous
related: troubleshooting, oomkilled, liveness-probe, rollback, proc-diagnosticare-pod, proc-visualizzare-log
---

## In parole semplici

**CrashLoopBackOff** non è un errore in sé: è lo stato di attesa in cui Kubernetes mette un container che continua a terminare. Il container parte, il processo principale esce (per un errore o anche normalmente), il kubelet lo riavvia, esce di nuovo… e tra un tentativo e l'altro aspetta sempre di più. La causa vera è sempre **dentro il container**: un errore dell'applicazione, una configurazione sbagliata, una dipendenza non raggiungibile, memoria insufficiente o una liveness probe troppo aggressiva.

## Dettagli tecnici

- Con `restartPolicy: Always` (default per Deployment, StatefulSet, DaemonSet) il kubelet riavvia il container ogni volta che termina. Il ritardo cresce in modo esponenziale: 10s, 20s, 40s… fino a un massimo di 5 minuti. Il contatore si azzera dopo 10 minuti di esecuzione senza problemi.
- Durante l'attesa il container è in `state.waiting.reason: CrashLoopBackOff`; l'ultima uscita è in `lastState.terminated` con `exitCode`, `reason` e orari.
- Codici di uscita utili:

| Exit code | Significato tipico |
|---|---|
| 0 | il processo è terminato normalmente (ad esempio un'immagine senza processo in foreground) |
| 1 | errore generico dell'applicazione |
| 126 / 127 | comando non eseguibile / non trovato (`command` o `args` errati) |
| 137 | ucciso con SIGKILL: spesso [OOMKilled](guide:oomkilled) o liveness probe fallita |
| 139 | segmentation fault |
| 143 | SIGTERM, terminazione richiesta |

- Se la liveness probe fallisce, gli eventi riportano `Liveness probe failed` e `Container ... failed liveness probe, will be restarted`.

## Esempio

```bash
kubectl get pod api-6c8d9f7b4-q7wzn -n shop
# NAME                    READY   STATUS             RESTARTS      AGE
# api-6c8d9f7b4-q7wzn     0/1     CrashLoopBackOff   6 (2m ago)    9m

kubectl describe pod api-6c8d9f7b4-q7wzn -n shop | grep -A5 "Last State"
kubectl logs api-6c8d9f7b4-q7wzn -n shop --previous --tail=100
```

Output dei log tipico: `Error: connect ECONNREFUSED 10.96.12.4:5432` indica che il database non è raggiungibile.

## Cosa può andare storto

- I log dell'istanza corrente sono vuoti perché il container è in attesa: bisogna leggere quelli **precedenti**.
- Il crash è dovuto a una variabile d'ambiente o a un file di ConfigMap/Secret modificato di recente.
- Una dipendenza (database, API esterna) non è pronta e l'applicazione esce invece di riprovare.
- La liveness probe parte prima che l'applicazione abbia finito l'avvio (manca `startupProbe` o `initialDelaySeconds` è troppo basso).
- Un nuovo rilascio ha introdotto un bug: tutti i pod nuovi vanno in crash mentre quelli vecchi funzionano.

## Come verificare

1. Nel [Centro Operativo](app:/operations-center) il problema compare come CrashLoopBackOff con il pod coinvolto.
2. Apri il pod da [Applicazioni → Pod](app:/k8s/pods): in **Panoramica** guarda riavvii, exit code e motivo dell'ultima terminazione.
3. Nella scheda **Log** seleziona il container e l'opzione per l'istanza precedente; cerca le ultime righe prima dell'uscita.
4. Nella scheda **Eventi** cerca `BackOff`, `Liveness probe failed`, `OOMKilling`.
5. In **Metriche** verifica se la memoria cresce fino al limite prima di ogni crash.

## Come risolvere

1. Se il problema è comparso dopo un rilascio, esegui un [rollback](guide:proc-rollback) dalla pagina [Rollout](app:/operations/rollout): è l'azione più rapida per ripristinare il servizio.
2. Errore applicativo o di configurazione: correggi ConfigMap, Secret o variabili e poi esegui un restart da [Operazioni → Restart](app:/operations/restart).
3. Exit code 137 con `OOMKilled`: segui [OOMKilled](guide:oomkilled).
4. Liveness probe: aumenta `initialDelaySeconds`, `timeoutSeconds` o `failureThreshold`, oppure aggiungi una `startupProbe` (vedi [Liveness probe](guide:liveness-probe)).
5. Exit code 0 o 127: controlla `command` e `args` nel tab **YAML**, valida con il dry-run e applica.

Riavviare il pod senza correggere la causa non serve: il contatore riparte, ma il crash si ripresenta.
