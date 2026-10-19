---
title: Rollback
summary: Tornare rapidamente a una versione precedente di un'applicazione che funzionava.
category: reliability
order: 30
keywords: rollback, undo, revisione, rollout history, ripristino versione
related: rolling-update, deployment, replicaset, proc-rollback, proc-gestione-incidenti
---

## In parole semplici

Il **rollback** è il "torna indietro" di un'applicazione. Se hai appena pubblicato una nuova versione e qualcosa non va (errori, crash, lentezza), con un rollback Kubernetes riporta i Pod alla configurazione di una revisione precedente, con lo stesso meccanismo graduale del [rolling update](guide:rolling-update).

È spesso il modo più veloce per ristabilire il servizio: prima si ripristina, poi si indaga con calma.

## Dettagli tecnici

- Ogni modifica a `spec.template` di un Deployment crea una **revisione**, cioè un ReplicaSet con l'annotazione `deployment.kubernetes.io/revision`.
- Il rollback copia il template del ReplicaSet scelto nel Deployment. Il risultato è una **nuova** revisione con numero più alto (la revisione di origine sparisce dalla lista perché viene "promossa").
- Sono disponibili solo le revisioni ancora conservate (`spec.revisionHistoryLimit`, default 10). Con `revisionHistoryLimit: 0` il rollback è impossibile.
- Il rollback riguarda **solo il template del Pod**. Non ripristina:
  - il numero di repliche;
  - ConfigMap e Secret referenziati (se li hai modificati, il contenuto resta quello nuovo);
  - dati su volumi persistenti o migrazioni di database già eseguite;
  - Service, Ingress e altre risorse.
- StatefulSet e DaemonSet conservano la storia tramite oggetti `ControllerRevision`; `kubectl rollout undo` funziona anche per loro.
- Se il Deployment è gestito da GitOps (Argo CD, Flux) il rollback manuale verrà sovrascritto: il rollback va fatto nel repository.

## Esempio

Alternativa da shell (per amministratori):

```bash
# Elenco delle revisioni
kubectl -n shop rollout history deployment/web

# Dettaglio di una revisione
kubectl -n shop rollout history deployment/web --revision=7

# Ritorno alla revisione precedente o a una specifica
kubectl -n shop rollout undo deployment/web
kubectl -n shop rollout undo deployment/web --to-revision=7

kubectl -n shop rollout status deployment/web
```

Per rendere leggibile la storia, annota il motivo di ogni modifica:

```bash
kubectl -n shop annotate deployment/web kubernetes.io/change-cause="web 1.5.0: nuovo checkout"
```

## Cosa può andare storto

- **Nessuna revisione disponibile**: la storia è stata potata o il workload è stato ricreato da zero.
- **Rollback inefficace**: il problema era in una ConfigMap, in un Secret o nel database, non nell'immagine.
- **Migrazioni irreversibili**: la vecchia versione non è compatibile con lo schema dati aggiornato.
- **Immagine non più disponibile** nel registry (tag cancellato): i Pod ripristinati vanno in `ImagePullBackOff`.
- **Sovrascrittura** da parte di pipeline CI/CD o GitOps.

## Come verificare

- [Operazioni → Rollout](app:/operations/rollout) mostra la revisione corrente, l'elenco delle revisioni e lo stato di avanzamento.
- Nella scheda **YAML** del Deployment controlla l'immagine effettiva; nella scheda **Eventi** vedi la scalatura dei ReplicaSet.
- Verifica che le repliche siano tutte pronte e che il [Centro Operativo](app:/operations-center) non segnali più errori.
- Ogni rollback eseguito dall'applicazione è registrato nell'[Audit Log](app:/security/audit).

## Come risolvere

1. Segui la procedura [Eseguire un rollback](guide:proc-rollback): scegli la revisione funzionante, conferma e attendi il completamento.
2. Se il rollback non risolve, controlla le modifiche a ConfigMap/Secret e ripristinale dalla scheda **YAML** o dall'export dei manifest.
3. Dopo il ripristino, analizza la versione problematica in un ambiente di test prima di ripubblicarla.
4. Documenta l'accaduto seguendo [Gestione incidenti](guide:proc-gestione-incidenti).
