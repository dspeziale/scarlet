---
title: Diagnosticare un Pod
summary: Procedura passo passo per capire perché un Pod non parte, si riavvia o non risponde.
category: procedures
order: 80
keywords: diagnosi, pod, eventi, log, describe, crashloopbackoff, pending, troubleshooting
related: troubleshooting, pod, crashloopbackoff, imagepullbackoff, oomkilled, pending, proc-visualizzare-log
---

## Quando serve

Usa questa procedura quando un Pod non è nello stato atteso: resta in `Pending`, va in `CrashLoopBackOff`, mostra `ImagePullBackOff` o `ErrImagePull`, è stato terminato per `OOMKilled`, oppure risulta `Running` ma l'applicazione non risponde. Di solito il problema compare prima nel [Centro Operativo](app:/operations-center) o nella campanella delle notifiche.

## Prerequisiti

- Utente con ruolo **Operator** o **Administrator** (il ruolo Viewer può vedere stato ed eventi, ma per i log serve almeno Operator).
- Scarlet in modalità LIVE e collegato al cluster (badge verde "LIVE" in alto).
- Conoscere il namespace dell'applicazione.

## Procedura

1. **Parti dal problema rilevato.** Apri il [Centro Operativo](app:/operations-center) e cerca la voce relativa al Pod. Leggi severità, rischio e azioni suggerite: spesso indicano già la causa probabile.
2. **Apri il dettaglio del Pod.** Vai su [Applicazioni → Pod](app:/k8s/pods), filtra per namespace e clicca sul Pod. Nella scheda **Panoramica** annota fase (`Pending`, `Running`, `Failed`...), numero di riavvii, nodo assegnato e stato di ogni container.
3. **Leggi gli eventi.** Apri la scheda **Eventi**. Gli eventi di tipo `Warning` sono i più utili: `FailedScheduling` (nessun nodo adatto), `Failed` con `ErrImagePull` (immagine o credenziali), `BackOff` (container che riparte), `Unhealthy` (probe fallite), `FailedMount` (volume non montabile).
4. **Leggi i log.** Apri la scheda **Log**, scegli il container e mostra le ultime 200-500 righe. Se il container si è riavviato, i log utili sono spesso quelli dell'istanza precedente: confrontali con l'errore che compare subito prima dell'uscita. Vedi [Visualizzare i log](guide:proc-visualizzare-log).
5. **Usa la scheda Diagnostica.** Riassume le condizioni del Pod, l'ultimo stato terminato (`lastState.terminated.reason` ed `exitCode`) e i controlli automatici. Un `exitCode` 137 con motivo `OOMKilled` indica memoria insufficiente; un `exitCode` 1 indica di solito un errore applicativo.
6. **Controlla le relazioni.** Nella scheda **Relazioni** verifica a quale Deployment/StatefulSet appartiene il Pod, quali Service lo selezionano, quali ConfigMap, Secret e PVC usa. Un ConfigMap o Secret mancante produce `CreateContainerConfigError`; un PVC `Pending` blocca il Pod in `Pending`.
7. **Controlla le metriche.** Nella scheda **Metriche** guarda CPU e memoria rispetto a request e limit (richiede metrics-server; altrimenti vedrai "Metriche avanzate non configurate").
8. **Confronta lo YAML.** Nella scheda **YAML** verifica immagine, tag, variabili, probe e risorse. Correggi sempre sul controller (Deployment, StatefulSet...), non sul singolo Pod: il Pod verrebbe ricreato con la configurazione vecchia.
9. **Decidi e agisci.** In base alla causa: correggi l'immagine, aumenta il limite di memoria, crea il Secret mancante, esegui un [rollback](guide:proc-rollback) o un riavvio da [Operazioni → Restart](app:/operations/restart).

Equivalenti da shell (per un amministratore):

```bash
kubectl -n shop get pod web-7c9f8d6b5-x2kqp -o wide
kubectl -n shop describe pod web-7c9f8d6b5-x2kqp
kubectl -n shop logs web-7c9f8d6b5-x2kqp -c web --tail=200
kubectl -n shop logs web-7c9f8d6b5-x2kqp -c web --previous
kubectl -n shop get events --field-selector involvedObject.name=web-7c9f8d6b5-x2kqp
```

## Verifica

- Il Pod è in fase `Running` e tutti i container risultano `Ready`.
- Il contatore dei riavvii non aumenta più per almeno qualche minuto.
- Il problema sparisce dal Centro Operativo (o puoi segnarlo come gestito nel Notification Center).
- Il Service collegato ha di nuovo endpoint attivi in [Networking → Endpoints](app:/k8s/endpoints).

## Se qualcosa va storto

- **Non vedi i log**: il container potrebbe non essere mai partito (immagine non scaricata, configurazione mancante). In quel caso la causa è negli eventi, non nei log.
- **Il Pod sparisce mentre lo analizzi**: il controller lo ha sostituito. Cerca il nuovo Pod con lo stesso prefisso di nome.
- **La modifica allo YAML non ha effetto**: probabilmente hai modificato il Pod e non il controller. Applica la correzione al Deployment.
- **Più Pod hanno lo stesso problema su un solo nodo**: il guasto è probabilmente del nodo. Segui [Verificare un nodo](guide:proc-verificare-nodo).
- Per i singoli errori consulta [CrashLoopBackOff](guide:crashloopbackoff), [ImagePullBackOff](guide:imagepullbackoff), [OOMKilled](guide:oomkilled) e [Pending](guide:pending).
