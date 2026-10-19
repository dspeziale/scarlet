---
title: Visualizzare i log
summary: Leggi, filtra, segui in tempo reale e scarica i log dei container per capire cosa sta facendo un'applicazione.
category: procedures
order: 70
keywords: log, logs, streaming, tail, previous, container, diagnostica, download
related: pod, container, proc-diagnosticare-pod, crashloopbackoff, troubleshooting
---

## Quando serve

- Un'applicazione restituisce errori o si comporta in modo inatteso.
- Un Pod è in **CrashLoopBackOff** e devi capire perché il processo termina.
- Vuoi seguire in tempo reale l'avvio di una nuova versione dopo un deploy.

## Prerequisiti

- Ruolo **Operator** o **Administrator** (il ruolo Viewer non ha accesso ai log).
- I log di Kubernetes contengono solo ciò che il processo scrive su **stdout/stderr**. Se l'applicazione scrive su file interni al container, qui non li vedrai.
- Kubernetes conserva i log del container attuale e, al massimo, di quello **precedente** (dopo un riavvio). I log dei Pod cancellati non sono più disponibili, a meno di un sistema di raccolta centralizzato.

## Procedura

1. Apri [Monitoraggio → Log](app:/monitoring/logs), oppure la scheda **Log** nella pagina di dettaglio di un Pod.
2. Scegli **Pod** e **container**. Se il Pod ha più container (sidecar, init container), selezionare quello giusto è fondamentale.
3. Imposta quante righe leggere (**tail**, massimo 5000 per richiesta) e, se vuoi, da quando (**since**, es. ultimi 15 minuti). Attiva i **timestamp** per correlare i log con gli eventi.
4. Per un container che si riavvia, leggi i log dell'istanza **precedente**: è lì che trovi il messaggio con cui il processo è terminato.
5. Per seguire in tempo reale avvia lo **streaming**. Puoi metterlo in **pausa** e riprenderlo. Lo streaming si ferma da solo dopo 30 minuti o 20.000 righe, per non sovraccaricare il browser e l'API server: se serve, riavvialo.
6. Usa **cerca/filtra** per isolare le righe utili (`ERROR`, `Exception`, un ID di richiesta).
7. Se devi allegare i log a un ticket o passarli a uno sviluppatore, usa **scarica**. Prima di condividerli verifica che non contengano dati sensibili.

Equivalente da shell:

```bash
kubectl -n produzione logs ordini-api-7d9f8b6c4-x2k1p -c app --tail=200 --timestamps
kubectl -n produzione logs ordini-api-7d9f8b6c4-x2k1p -c app --previous
kubectl -n produzione logs -f deployment/ordini-api --since=10m
```

Per un container Podman (fuori da Kubernetes):

```bash
sudo podman logs --tail 200 -t nome-container
```

## Verifica

- Vedi righe con timestamp coerenti con l'orario dell'evento che stai indagando.
- Hai individuato il messaggio di errore e la sua prima occorrenza: annotala, servirà per la diagnosi e per l'eventuale rapporto sull'incidente.

## Se qualcosa va storto

- **Nessun log**: il container potrebbe non essere mai partito (es. ImagePullBackOff o CreateContainerConfigError). In quel caso guarda la scheda **Eventi**, non i log. Vedi [Diagnosticare un Pod](guide:proc-diagnosticare-pod).
- **`previous terminated container not found`**: il container non si è mai riavviato, oppure il Pod è stato ricreato con un nome nuovo.
- **Log tagliati**: hai raggiunto il limite di righe; restringi con **since** o fai più richieste.
- **Lo streaming si interrompe**: limite di 30 minuti/20.000 righe, oppure il Pod è stato ricreato; riavvia lo streaming sul nuovo Pod.
- **Accesso negato**: il tuo ruolo non comprende la lettura dei log; chiedi a un Administrator.
