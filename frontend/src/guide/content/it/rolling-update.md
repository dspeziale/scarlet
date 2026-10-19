---
title: Rolling update
summary: Aggiornamento progressivo dei Pod senza interrompere il servizio.
category: reliability
order: 20
keywords: rolling update, rollout, aggiornamento, maxSurge, maxUnavailable, revisione
related: deployment, replicaset, rollback, readiness-probe, proc-pubblicare-applicazione, proc-rollback
---

## In parole semplici

Quando aggiorni un'applicazione (per esempio cambi la versione dell'immagine), Kubernetes non spegne tutto e riaccende: sostituisce i Pod **un po' alla volta**. Crea alcuni Pod nuovi, aspetta che siano pronti, poi elimina alcuni dei vecchi, e così via. Gli utenti continuano a essere serviti per tutto il tempo.

Questo processo si chiama **rolling update**; l'operazione complessiva si chiama **rollout**.

## Dettagli tecnici

- Un rollout parte quando cambia il **template del Pod** (`spec.template`): immagine, variabili d'ambiente, risorse, label del template. Modificare solo `replicas` non crea un nuovo rollout.
- Il Deployment crea un **nuovo ReplicaSet** (nuova revisione) e lo scala verso l'alto mentre scala verso il basso il vecchio. I vecchi ReplicaSet restano (a zero repliche) per permettere il [rollback](guide:rollback); quanti ne restano dipende da `spec.revisionHistoryLimit` (default 10).
- Parametri in `spec.strategy.rollingUpdate`:
  - `maxSurge`: quanti Pod in più rispetto a `replicas` possono esistere durante l'aggiornamento (default 25%).
  - `maxUnavailable`: quanti Pod possono essere non disponibili (default 25%).
- `minReadySeconds`: per quanti secondi un Pod deve restare Ready prima di essere considerato disponibile.
- `progressDeadlineSeconds` (default 600): se il rollout non progredisce entro questo tempo, la condition `Progressing` diventa `False` con reason `ProgressDeadlineExceeded`. Kubernetes **non** esegue rollback automatico.
- La strategia alternativa `Recreate` elimina tutti i Pod vecchi prima di creare i nuovi (con interruzione).
- Gli StatefulSet aggiornano un Pod alla volta in ordine inverso (`RollingUpdate`), i DaemonSet un nodo alla volta secondo il proprio `maxUnavailable`.
- Il rolling update è sicuro solo se la [readiness probe](guide:readiness-probe) è affidabile: senza probe, un Pod è considerato pronto appena il container parte.

## Esempio

```yaml
spec:
  replicas: 4
  minReadySeconds: 10
  revisionHistoryLimit: 10
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 0
```

Con `maxSurge: 1` e `maxUnavailable: 0` la capacità non scende mai sotto 4 Pod pronti.

Alternativa da shell:

```bash
kubectl -n shop set image deployment/web web=registry.example.com/shop/web:1.5.0
kubectl -n shop rollout status deployment/web
kubectl -n shop rollout history deployment/web
```

## Cosa può andare storto

- **Rollout bloccato**: i nuovi Pod finiscono in `ImagePullBackOff` o `CrashLoopBackOff`; con `maxUnavailable: 0` i vecchi restano attivi e il servizio regge, ma l'aggiornamento non finisce.
- **Nuovi Pod in Pending**: con `maxSurge` serve capacità extra sul cluster.
- **Readiness assente o troppo permissiva**: il traffico arriva a Pod non ancora pronti, errori 5xx durante l'aggiornamento.
- **Incompatibilità tra versioni**: per qualche minuto convivono vecchia e nuova versione (schema DB, API): l'applicazione deve tollerarlo.
- **Tag `latest`**: cambiare l'immagine sotto lo stesso tag non crea un rollout e rende difficile capire cosa gira.

## Come verificare

- [Operazioni → Rollout](app:/operations/rollout) mostra lo stato del rollout, le revisioni e i comandi pausa/riprendi.
- Nel dettaglio del Deployment, la scheda **Eventi** mostra le scalature dei ReplicaSet e la scheda **Relazioni** i ReplicaSet vecchio e nuovo.
- Il [Centro Operativo](app:/operations-center) segnala Pod in errore e deployment degradati.

## Come risolvere

1. Se il rollout è bloccato, apri un Pod nuovo e leggi **Eventi** e **Log** per capire la causa.
2. Se il problema è nella nuova versione, esegui un [rollback](guide:proc-rollback) dalla pagina Rollout.
3. Puoi mettere in **pausa** il rollout per indagare e **riprenderlo** dopo la correzione.
4. Correggi la configurazione (immagine, risorse, probe) e applica di nuovo: partirà una nuova revisione.
