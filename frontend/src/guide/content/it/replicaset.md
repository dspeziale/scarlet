---
title: ReplicaSet
summary: Garantisce che sia sempre in esecuzione il numero richiesto di Pod identici.
category: workloads
order: 20
keywords: replicaset, repliche, selector, owner reference, revisione
related: deployment, pod, replica, rolling-update, rollback
---

## In parole semplici

Un **ReplicaSet** è un "contatore con le mani": osserva quanti Pod con certe etichette esistono e, se sono meno del previsto, ne crea altri; se sono di più, ne elimina alcuni. Tutto qui.

Nella pratica quotidiana **non si crea quasi mai un ReplicaSet a mano**: lo crea e lo gestisce un [Deployment](guide:deployment). Ogni versione del Deployment corrisponde a un ReplicaSet diverso; durante un aggiornamento il ReplicaSet nuovo cresce mentre quello vecchio si riduce.

## Dettagli tecnici

- `spec.replicas`, `spec.selector` e `spec.template` hanno lo stesso significato visto nel Deployment.
- Il controller ReplicaSet "adotta" qualsiasi Pod che corrisponde al selector e non ha già un proprietario. Per questo due workload con selector sovrapposti si contendono i Pod: va evitato.
- Ogni Pod creato ha una `metadata.ownerReferences` che punta al ReplicaSet, che a sua volta punta al Deployment. Scarlet usa queste relazioni nella scheda **Relazioni** della pagina di dettaglio.
- Il nome del ReplicaSet è `<deployment>-<pod-template-hash>`; l'etichetta `pod-template-hash` viene aggiunta ai Pod per distinguere le versioni.
- L'annotazione `deployment.kubernetes.io/revision` indica il numero di revisione usato dal [rollback](guide:rollback).
- Modificare direttamente il template di un ReplicaSet gestito da un Deployment è inutile: il Deployment lo riporta allo stato dichiarato. Il ReplicaSet non aggiorna i Pod esistenti quando cambi il template: si applica solo ai nuovi.

I ReplicaSet vecchi rimangono con `replicas: 0` (fino a `revisionHistoryLimit`) e non consumano risorse.

## Esempio

Vedere i ReplicaSet di un Deployment e le loro revisioni (alternativa da shell):

```bash
kubectl -n shop get rs -l app=web
# NAME             DESIRED   CURRENT   READY   AGE
# web-7d9c6b8f5c   3         3         3       2d
# web-5f4b7c9d8a   0         0         0       9d
kubectl -n shop rollout history deployment/web
```

## Cosa può andare storto

- **DESIRED diverso da READY** per molto tempo: i Pod non partono o non superano la readiness. La causa è nei Pod, non nel ReplicaSet.
- **Due ReplicaSet attivi con repliche > 0** per molto tempo: un rollout è bloccato a metà.
- **ReplicaSet orfani** (senza Deployment proprietario) creati da vecchi manifest o da cancellazioni con `--cascade=orphan`: continuano a far girare Pod che nessuno gestisce.
- **Quota del namespace superata**: l'evento `FailedCreate` sul ReplicaSet indica che i Pod non possono essere creati (ad esempio per un ResourceQuota).

## Come verificare

In Scarlet apri il Deployment, scheda **Relazioni**, e seleziona il ReplicaSet: vedi repliche desiderate/correnti/pronte e i suoi eventi. Cerca eventi `FailedCreate`.

```bash
kubectl -n shop describe rs web-7d9c6b8f5c
kubectl -n shop get events --field-selector involvedObject.name=web-7d9c6b8f5c
```

## Come risolvere

1. Se l'evento è `FailedCreate`, leggi il messaggio: quota, permessi o admission webhook che rifiuta il Pod.
2. Se i Pod esistono ma non sono pronti, passa alla diagnostica del Pod: [Diagnosticare un Pod](guide:proc-diagnosticare-pod).
3. Se un rollout è bloccato con due ReplicaSet attivi, valuta un [rollback](guide:rollback) dalla pagina [Rollout](app:/operations/rollout).
4. Elimina i ReplicaSet orfani solo dopo aver verificato che nessun servizio dipenda dai loro Pod.
5. Non modificare i ReplicaSet gestiti: agisci sempre sul Deployment.
