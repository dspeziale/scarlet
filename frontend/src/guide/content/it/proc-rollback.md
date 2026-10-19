---
title: Eseguire un rollback
summary: Come riportare un Deployment a una revisione precedente quando un aggiornamento causa problemi.
category: procedures
order: 100
keywords: rollback, rollout, revisione, undo, deployment, ripristino versione
related: rollback, rolling-update, deployment, replicaset, proc-diagnosticare-pod, proc-gestione-incidenti
---

## Quando serve

Dopo un aggiornamento (nuova immagine, nuove variabili, nuove risorse) l'applicazione peggiora: i nuovi Pod vanno in `CrashLoopBackOff` o `ImagePullBackOff`, il rollout non avanza, aumentano gli errori o la latenza. Il rollback è il modo più rapido per tornare a una versione nota e funzionante, prima ancora di aver capito la causa.

> Il rollback ripristina il **template dei Pod** (immagine, variabili, probe, risorse). Non ripristina dati nei volumi, schemi di database, ConfigMap o Secret modificati separatamente.

## Prerequisiti

- Ruolo **Operator** o **Administrator**.
- La risorsa è un Deployment (o DaemonSet/StatefulSet, che hanno anch'essi una cronologia di revisioni).
- Esiste una revisione precedente: Kubernetes conserva i vecchi ReplicaSet secondo `spec.revisionHistoryLimit` (default 10). Se è impostato a 0 non c'è nulla a cui tornare.

## Procedura

1. **Verifica la situazione.** Apri [Operazioni → Rollout](app:/operations/rollout) e seleziona namespace e Deployment. Lo stato mostra repliche aggiornate, disponibili e non disponibili e se il rollout è in corso, completato o bloccato (`ProgressDeadlineExceeded`).
2. **Se il rollout è ancora in corso, mettilo in pausa** con **Pausa**: eviti che altri Pod vengano sostituiti mentre decidi.
3. **Consulta la cronologia.** Nella lista delle revisioni ogni voce mostra numero di revisione, immagine e data. Individua l'ultima revisione funzionante (di solito quella immediatamente precedente).
4. **Confronta.** Se disponibile, guarda la differenza tra la revisione attuale e quella scelta, per essere sicuro di cosa cambierà.
5. **Esegui il rollback.** Seleziona la revisione e conferma **Rollback**. Se il Deployment era in pausa, usa poi **Riprendi**: un Deployment in pausa non applica modifiche al template.
6. **Segui l'avanzamento.** Il rollback è a sua volta un rolling update: i Pod della revisione scelta sostituiscono progressivamente quelli difettosi, rispettando `maxUnavailable` e `maxSurge`.
7. **Registra l'intervento.** L'azione è tracciata nell'[Audit Log](app:/security/audit). Segna il problema come gestito nel Notification Center e annota la causa per chi dovrà correggere la nuova versione.

Equivalenti da shell:

```bash
kubectl -n shop rollout status deployment/web
kubectl -n shop rollout history deployment/web
kubectl -n shop rollout history deployment/web --revision=7
kubectl -n shop rollout undo deployment/web --to-revision=7
```

Nota: dopo il rollback la revisione ripristinata assume un **nuovo numero** (ad esempio la 7 diventa la 9). È il comportamento normale di Kubernetes.

## Verifica

- In [Rollout](app:/operations/rollout) lo stato è completato e tutte le repliche sono aggiornate e disponibili.
- Nel dettaglio del Deployment l'immagine è quella attesa.
- I Pod sono `Running` e `Ready`, senza riavvii crescenti.
- Il problema sparisce dal [Centro Operativo](app:/operations-center).
- L'applicazione risponde correttamente (controlla con il test funzionale abituale).

## Se qualcosa va storto

- **Nessuna revisione disponibile**: la cronologia è vuota o `revisionHistoryLimit` è troppo basso. Ripristina manualmente l'immagine precedente dalla scheda YAML o da [Operazioni → Deploy](app:/operations/deploy).
- **Il rollback non parte**: il Deployment è in pausa. Premi **Riprendi**.
- **Anche la revisione precedente fallisce**: la causa non è nel template ma all'esterno (ConfigMap, Secret, database, nodo, registry). Segui [Diagnosticare un Pod](guide:proc-diagnosticare-pod).
- **Il rollout resta bloccato**: controlla Pod `Pending` per risorse insufficienti o PodDisruptionBudget troppo restrittivi.
- **Dati incompatibili**: se la nuova versione ha migrato il database, la vecchia potrebbe non funzionare. In quel caso serve il piano di ripristino dell'applicazione, non solo il rollback Kubernetes.
