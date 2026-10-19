---
title: Job
summary: Esegue un'attività fino al completamento, ripetendola in caso di errore entro un limite.
category: workloads
order: 50
keywords: job, batch, completions, parallelism, backoffLimit, migrazione, ttl
related: cronjob, pod, pod-failed-unknown, resource-limit, troubleshooting
---

## In parole semplici

Un **Job** serve per lavori che **hanno una fine**: una migrazione di database, un'importazione di file, un report notturno, una pulizia. Kubernetes avvia uno o più Pod, aspetta che terminino con successo e poi considera il Job **completato**.

A differenza di un [Deployment](guide:deployment), un Pod di Job che termina correttamente **non viene riavviato**. Se invece fallisce, il Job ci riprova un certo numero di volte.

## Dettagli tecnici

- `spec.completions`: quanti completamenti con successo servono (default 1).
- `spec.parallelism`: quanti Pod possono girare contemporaneamente (default 1).
- `spec.backoffLimit`: numero di tentativi falliti prima di dichiarare il Job fallito (default 6). Tra un tentativo e l'altro c'è un ritardo esponenziale (10s, 20s, 40s... fino a 6 minuti).
- `spec.activeDeadlineSeconds`: tempo massimo totale; superato, i Pod vengono terminati e il Job fallisce con motivo `DeadlineExceeded`.
- `spec.ttlSecondsAfterFinished`: cancella automaticamente il Job (e i suoi Pod) dopo il termine, utile per non accumulare oggetti.
- `spec.template.spec.restartPolicy` deve essere `Never` o `OnFailure` (`Always` non è ammesso). Con `OnFailure` il container viene riavviato nello stesso Pod; con `Never` viene creato un Pod nuovo a ogni tentativo, e i Pod falliti restano disponibili per leggere i log.
- `spec.completionMode: Indexed` assegna a ogni Pod un indice (`JOB_COMPLETION_INDEX`) per suddividere il lavoro.
- Il template di un Job è immutabile: per cambiarlo si crea un nuovo Job.

Lo stato è in `status.succeeded`, `status.failed`, `status.active` e nelle condizioni `Complete` o `Failed`. In PKM: [Applicazioni → Jobs](app:/k8s/jobs).

## Esempio

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: db-migrate-1-4-2
  namespace: shop
spec:
  backoffLimit: 3
  activeDeadlineSeconds: 900
  ttlSecondsAfterFinished: 86400
  template:
    spec:
      restartPolicy: Never
      containers:
        - name: migrate
          image: registry.example.com/shop/web:1.4.2
          command: ["python", "manage.py", "migrate"]
          envFrom:
            - secretRef: { name: db-credentials }
          resources:
            requests: { cpu: 100m, memory: 256Mi }
            limits: { memory: 512Mi }
```

## Cosa può andare storto

- **BackoffLimitExceeded**: il programma esce con codice diverso da zero a ogni tentativo. Il Job finisce in `Failed`.
- **DeadlineExceeded**: il lavoro impiega più di `activeDeadlineSeconds`.
- **OOMKilled**: il Pod supera il limite di memoria; vedi [OOMKilled](guide:oomkilled).
- **Pod in Pending** per risorse insufficienti: il Job resta "attivo" senza fare nulla.
- **Lavoro eseguito due volte**: in rari casi (nodo perso, retry) un Job può avviare il lavoro più di una volta. Il codice deve essere **idempotente**.
- **Accumulo di Job vecchi** senza `ttlSecondsAfterFinished`.

## Come verificare

In PKM apri il Job: vedi completamenti riusciti/falliti, i Pod generati (scheda Relazioni) e i log dell'ultimo tentativo nella scheda Log del Pod.

```bash
kubectl -n shop get job db-migrate-1-4-2
kubectl -n shop describe job db-migrate-1-4-2
kubectl -n shop logs job/db-migrate-1-4-2
kubectl -n shop get pods -l job-name=db-migrate-1-4-2
```

## Come risolvere

1. Leggi i log del Pod fallito: il codice di uscita e l'ultimo errore applicativo sono la prima informazione utile.
2. Per `DeadlineExceeded` valuta se aumentare il tempo o se il lavoro è bloccato (connessione al database, lock).
3. Per OOMKilled aumenta il limite di memoria nel manifest.
4. Correggi la causa, elimina il Job fallito e creane uno nuovo (il template non è modificabile).
5. Imposta `ttlSecondsAfterFinished` per la pulizia automatica.
