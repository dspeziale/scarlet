---
title: Introduzione a Scarlet
summary: Cos'è Scarlet, come distinguere la modalità LIVE dalla DEMO e come usare questa guida.
category: intro
order: 10
keywords: introduzione, scarlet, pkm, live, demo, guida, metodo, centro operativo
related: cos-e-kubernetes, cos-e-podman, troubleshooting, proc-installare, faq
---

## Cos'è Scarlet

**Scarlet** (*Secure Cluster Administration, Runtime & Lifecycle Engineering Tool*) è una console operativa web per gestire in un unico posto un cluster **Kubernetes** e uno o più host **Podman**. È pensata per chi deve tenere in piedi le applicazioni ogni giorno: controllare lo stato, capire perché qualcosa non funziona, intervenire in modo sicuro e lasciare traccia di ciò che è stato fatto.

Scarlet non sostituisce `kubectl` o `podman`: li affianca. Tutto quello che fai dall'interfaccia passa dalle API ufficiali (Kubernetes API server e libpod REST API di Podman), con i permessi del ruolo assegnato al tuo utente. Ogni operazione rilevante viene registrata nell'[Audit Log](app:/security/audit).

Le aree principali del menu laterale sono:

- **Dashboard** e **Centro Operativo**: la sintesi dello stato e l'elenco dei problemi rilevati automaticamente, con gravità (CRITICAL, ERROR, WARNING, INFO), rischio e azioni suggerite.
- **Cluster**, **Applicazioni**, **Networking**, **Storage**, **Configurazione**: le risorse Kubernetes.
- **Container**: la parte Podman (container, immagini, registry).
- **Monitoraggio** e **Operazioni**: metriche, log, salute del sistema, alta affidabilità; onboarding di un'immagine e deploy guidato, scale, restart, rollout, applicazione di YAML, backup, manutenzione dei nodi.
- **Sicurezza** e **Impostazioni**: utenti, ruoli, audit, configurazione dell'applicazione.

Ogni risorsa ha una pagina di dettaglio con le schede **Panoramica**, **Relazioni**, **Eventi**, **Log** (per i pod), **Metriche**, **YAML** e **Diagnostica**.

## Modalità LIVE e DEMO

Scarlet può funzionare in due modalità, impostate nel file `/etc/pkm/config.yaml`:

| Modalità | Come la riconosci | Dati mostrati |
|---|---|---|
| **LIVE** | Badge verde "LIVE" con il nome del contesto del cluster | Dati reali del cluster e di Podman |
| **DEMO** | Banner a strisce "DEMO" in alto | Dati di esempio, nessun cluster reale |

La modalità DEMO (`mode: demo`, accettata solo con `environment: development`) serve per formazione e prove dell'interfaccia. **Non va mai usata in produzione**: le azioni non hanno effetto su sistemi reali e i dati non rappresentano nulla di vero. Prima di qualsiasi intervento, guarda sempre il badge in alto: se non vedi "LIVE" con il contesto atteso, fermati.

> Scarlet non inventa mai dati. Se metrics-server o Prometheus non sono configurati, le pagine di metriche mostrano "Metriche avanzate non configurate" invece di valori finti.

## Come usare questa guida

La guida è organizzata per categorie:

- **Introduzione**: cos'è Kubernetes, cos'è Podman, questa pagina.
- **Concetti**, **Workload**, **Networking**, **Storage**, **Configurazione**, **Affidabilità**: spiegano gli oggetti con cui lavori. Ogni articolo ha sempre le stesse sei sezioni: *In parole semplici*, *Dettagli tecnici*, *Esempio*, *Cosa può andare storto*, *Come verificare*, *Come risolvere*.
- **Troubleshooting**: un articolo per ogni stato di errore tipico (CrashLoopBackOff, ImagePullBackOff, OOMKilled, Pending...).
- **Procedure**: passi numerati per le attività operative (installare, collegare il cluster, fare un rollback, mettere un nodo in manutenzione, fare backup e restore...).
- **FAQ**: risposte rapide alle domande più frequenti.

Puoi cercare per parola chiave dalla pagina **Guida** del menu laterale e seguire i link "correlati" in fondo a ogni articolo. Dove utile, gli articoli riportano anche i comandi `kubectl` o `podman` equivalenti, da usare su una shell se hai accesso amministrativo.

## Il metodo: Capire, Diagnosticare, Decidere, Agire, Verificare

Davanti a un problema, segui sempre questi cinque passi. Evitano gli interventi "a istinto" che spesso peggiorano la situazione.

1. **Capire**: cosa sta succedendo e quanto è grave? Parti dal [Centro Operativo](app:/operations-center): ti dice quale risorsa è coinvolta, con che gravità e qual è il rischio.
2. **Diagnosticare**: perché succede? Apri la risorsa e guarda le schede **Eventi**, **Log** e **Diagnostica**. Leggi l'articolo della guida collegato al problema.
3. **Decidere**: quale intervento è il più piccolo e reversibile? Un rollback è quasi sempre più sicuro di una modifica a caldo. Se il servizio è critico, avvisa prima chi di dovere.
4. **Agire**: esegui l'azione dalla pagina corretta (Operazioni, Rollout, YAML con dry-run). Il tuo ruolo determina cosa puoi fare.
5. **Verificare**: il problema è sparito? Controlla che il pod sia Ready, che gli eventi non mostrino nuovi errori e che il Centro Operativo non segnali più la risorsa. Poi segna il problema come gestito dal Notification Center (icona a campana).

## Ruoli in breve

- **Administrator**: può fare tutto, incluse impostazioni, utenti e la visualizzazione dei valori dei Secret (azione registrata).
- **Operator**: monitoraggio, deploy (wizard e YAML dei tipi applicativi), scale, restart, rollout, log, troubleshooting, start/stop/restart dei container Podman.
- **Viewer**: sola lettura, senza log e senza valori dei Secret.

I permessi sono applicati dal backend: se un pulsante non c'è o restituisce un errore di autorizzazione, è il tuo ruolo che non lo consente.
