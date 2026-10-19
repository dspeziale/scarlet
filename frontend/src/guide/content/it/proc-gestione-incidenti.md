---
title: Gestire un incidente
summary: Metodo operativo per affrontare un disservizio, dal primo allarme alla chiusura, usando Centro Operativo e notifiche.
category: procedures
order: 140
keywords: incidente, disservizio, centro operativo, notifiche, severità, critical, escalation, post-mortem
related: troubleshooting, proc-diagnosticare-pod, proc-rollback, proc-verificare-nodo, monitoring, introduzione
---

## Quando serve

Quando un servizio è degradato o non disponibile: utenti che segnalano errori, un problema `CRITICAL` o `ERROR` nel Centro Operativo, un nodo `NotReady`, un Deployment senza repliche disponibili. La procedura applica il metodo della guida: **Capire → Diagnosticare → Decidere → Agire → Verificare**.

## Prerequisiti

- Ruolo **Operator** per diagnosi e azioni correttive (restart, scale, rollback, cordon/drain); **Administrator** per azioni su Secret, utenti e impostazioni.
- Scarlet in modalità **LIVE** (badge verde con il contesto del cluster). Se vedi il banner a strisce "DEMO" stai guardando dati di esempio: non è il cluster reale.
- Sapere chi contattare per l'escalation (responsabile dell'applicazione, amministratore del cluster).

## Procedura

1. **Capire: valuta l'impatto.** Apri il [Centro Operativo](app:/operations-center). Ordina per severità:
   - `CRITICAL`: servizio fermo o a rischio immediato (es. nessuna replica disponibile, nodo NotReady);
   - `ERROR`: componente guasto ma servizio parzialmente attivo;
   - `WARNING`: degrado o rischio futuro;
   - `INFO`: informativo.
   Annota l'ora di inizio, le risorse colpite e il rischio indicato. Dalla campanella del Notification Center **segna il problema come preso in carico**, così i colleghi sanno che qualcuno se ne occupa.
2. **Capire: delimita il perimetro.** Un solo Pod, un intero Deployment, tutti i Pod di un nodo, o tutto il cluster? Controlla [Cluster → Panoramica](app:/cluster), [Cluster → Eventi](app:/cluster/events) e [Monitoraggio → Health](app:/monitoring/health).
3. **Diagnosticare: cerca cosa è cambiato.** Molti incidenti seguono una modifica. Consulta l'[Audit Log](app:/security/audit) (deploy, scale, rollout, modifiche YAML recenti) e la cronologia in [Operazioni → Rollout](app:/operations/rollout).
4. **Diagnosticare: analizza la risorsa.** Segui [Diagnosticare un Pod](guide:proc-diagnosticare-pod) o [Verificare un nodo](guide:proc-verificare-nodo): eventi, log, diagnostica, metriche.
5. **Decidere: prima ripristina, poi indaga.** Scegli l'azione meno rischiosa che riporta il servizio:
   - aggiornamento recente difettoso → [rollback](guide:proc-rollback);
   - processo bloccato senza cause evidenti → riavvio da [Operazioni → Restart](app:/operations/restart);
   - carico eccessivo → aumento repliche da [Operazioni → Scale](app:/operations/scale);
   - nodo guasto → cordon e drain da [Operazioni → Manutenzione](app:/operations/maintenance).
   Leggi i rischi indicati dall'app prima di confermare. Evita modifiche multiple contemporanee: non capiresti quale ha funzionato.
6. **Agire.** Esegui una sola azione alla volta e annota ora ed esito. Ogni azione resta registrata nell'Audit Log.
7. **Verificare.** Controlla che il problema sparisca dal Centro Operativo, che Pod e repliche siano `Ready` e che il servizio risponda dal punto di vista dell'utente.
8. **Escalation** se entro il tempo concordato (ad esempio 30 minuti) il servizio non è ripristinato, o se la causa è fuori da Scarlet (rete, storage, registry, database esterno).
9. **Chiudere.** Segna il problema come gestito nel Notification Center e scrivi un breve resoconto: cronologia, causa, azione risolutiva, azioni preventive (probe, limiti di memoria, repliche, PodDisruptionBudget).

## Verifica

- Nessun problema `CRITICAL` o `ERROR` aperto relativo all'incidente nel [Centro Operativo](app:/operations-center).
- Le repliche disponibili coincidono con quelle desiderate.
- La pagina [Health](app:/monitoring/health) è Healthy.
- Il servizio è confermato funzionante da chi lo usa.
- Il resoconto è scritto e condiviso.

## Se qualcosa va storto

- **Scarlet stesso non risponde**: controlla sul server `systemctl status pkm` e `journalctl -u pkm`. Nel frattempo puoi operare con `kubectl` da shell; il cluster continua a funzionare anche senza Scarlet.
- **Kubernetes Unhealthy nella pagina Health**: Scarlet non raggiunge l'API server. Verifica rete e kubeconfig, poi chiedi all'amministratore del cluster lo stato del control plane.
- **L'azione peggiora la situazione**: fermati, annulla l'ultima azione (ad esempio rollback del rollback, ritorno al numero di repliche precedente) e passa all'escalation.
- **Metriche non disponibili**: senza metrics-server o Prometheus Scarlet mostra "Metriche avanzate non configurate" e non stima i consumi; basati su eventi e log.
- **Troppi allarmi insieme**: parti dal livello più basso dell'infrastruttura (nodi, storage, rete). Un nodo guasto genera decine di problemi a cascata sui Pod.
