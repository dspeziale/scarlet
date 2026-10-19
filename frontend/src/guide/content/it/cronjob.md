---
title: CronJob
summary: Crea Job a orari prestabiliti, come il cron di Linux.
category: workloads
order: 60
keywords: cronjob, cron, schedule, pianificazione, concurrencyPolicy, suspend, timezone
related: job, pod, backup, troubleshooting
---

## In parole semplici

Un **CronJob** è un [Job](guide:job) programmato: "ogni notte alle 2:00 esegui la pulizia", "ogni 15 minuti sincronizza i dati". All'orario stabilito Kubernetes crea un nuovo Job, che a sua volta crea il Pod che fa il lavoro.

La sintassi dell'orario è quella classica del cron di Linux, quindi chi conosce `crontab` si trova subito a casa.

## Dettagli tecnici

- `spec.schedule`: espressione cron a cinque campi (`minuto ora giorno-mese mese giorno-settimana`), ad esempio `0 2 * * *`. Sono accettate anche macro come `@daily` o `@hourly`.
- `spec.timeZone`: fuso orario IANA (es. `Europe/Rome`). Se assente si usa il fuso del kube-controller-manager, spesso UTC: attenzione all'ora legale.
- `spec.concurrencyPolicy`: `Allow` (default, più esecuzioni possono sovrapporsi), `Forbid` (salta l'esecuzione se la precedente è ancora in corso), `Replace` (termina la precedente e avvia la nuova).
- `spec.startingDeadlineSeconds`: entro quanto tempo dall'orario previsto un'esecuzione mancata può ancora partire. Se il controller conta più di 100 esecuzioni mancate senza questo campo, smette di pianificare e registra un errore.
- `spec.suspend: true`: sospende le esecuzioni future senza cancellare il CronJob.
- `spec.successfulJobsHistoryLimit` (default 3) e `spec.failedJobsHistoryLimit` (default 1): quanti Job conclusi conservare.
- `spec.jobTemplate`: il modello del Job, con tutti i campi visti nella voce [Job](guide:job).

Lo stato mostra `lastScheduleTime`, `lastSuccessfulTime` e i Job attivi. In PKM: [Applicazioni → CronJobs](app:/k8s/cronjobs).

## Esempio

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: cleanup-sessions
  namespace: shop
spec:
  schedule: "0 2 * * *"
  timeZone: Europe/Rome
  concurrencyPolicy: Forbid
  startingDeadlineSeconds: 600
  successfulJobsHistoryLimit: 3
  failedJobsHistoryLimit: 3
  jobTemplate:
    spec:
      backoffLimit: 2
      template:
        spec:
          restartPolicy: OnFailure
          containers:
            - name: cleanup
              image: registry.example.com/shop/tools:2.1.0
              args: ["cleanup", "--older-than", "7d"]
```

## Cosa può andare storto

- **Non parte mai**: espressione cron sbagliata, CronJob sospeso, oppure fuso orario diverso da quello che pensi.
- **Esecuzioni sovrapposte** con `Allow`, che caricano il sistema o corrompono dati.
- **Esecuzioni saltate** con `Forbid` se il lavoro dura più dell'intervallo.
- **Job falliti ripetutamente**: il CronJob continua a crearne di nuovi a ogni orario; il problema è nel Job, non nella pianificazione.
- **"Too many missed start times"**: il controller ha perso troppe esecuzioni (ad esempio dopo un fermo del cluster) e smette di pianificare finché non imposti `startingDeadlineSeconds`.

## Come verificare

In PKM apri il CronJob: controlla pianificazione, fuso orario, stato di sospensione, ultima esecuzione e Job recenti nella scheda Relazioni. La scheda Eventi riporta errori di pianificazione.

```bash
kubectl -n shop get cronjob cleanup-sessions
kubectl -n shop get jobs --sort-by=.metadata.creationTimestamp
kubectl -n shop describe cronjob cleanup-sessions
```

## Come risolvere

1. Verifica l'espressione cron e imposta `timeZone` in modo esplicito.
2. Per provare subito il lavoro senza aspettare l'orario, un amministratore può creare un Job manuale dal CronJob: `kubectl -n shop create job --from=cronjob/cleanup-sessions test-manuale`.
3. Se il Job fallisce, segui la voce [Job](guide:job) e leggi i log del Pod.
4. Scegli `Forbid` per lavori che non devono sovrapporsi.
5. Per fermare temporaneamente le esecuzioni imposta `suspend: true` dalla scheda YAML.
