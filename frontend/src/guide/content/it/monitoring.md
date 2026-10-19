---
title: Monitoraggio
summary: Da dove arrivano metriche, eventi, log e stato di salute in PKM, e come leggerli senza farsi ingannare.
category: concepts
order: 70
keywords: monitoraggio, metriche, metrics-server, prometheus, health, eventi, log, cpu, memoria
related: resource-request, resource-limit, node, proc-visualizzare-log, troubleshooting, oomkilled
---

## In parole semplici

Monitorare significa sapere, in ogni momento, se le applicazioni e il cluster stanno bene e accorgersi dei problemi prima degli utenti. In PKM hai quattro fonti di informazione:

- **Metriche**: quanta CPU, memoria, disco e rete usano pod e nodi.
- **Eventi**: cosa è appena successo nel cluster (pod creati, pull falliti, scheduling impossibile...).
- **Log**: cosa scrivono le applicazioni.
- **Health**: se PKM stesso e i sistemi a cui è collegato funzionano.

Il [Centro Operativo](app:/operations-center) combina queste fonti e ti mostra i problemi già interpretati.

## Dettagli tecnici

**Metriche CPU/RAM** di pod e nodi provengono da **metrics-server** (API `metrics.k8s.io`). Sono valori istantanei, campionati circa ogni 15 secondi, senza storico. **Storico e metriche di rete** provengono da **Prometheus**, se configurato in [Impostazioni → Kubernetes](app:/settings/kubernetes). Se nessuno dei due è disponibile, PKM mostra "Metriche avanzate non configurate": **non stima e non inventa valori**.

Come leggere i numeri:

- CPU in **millicore** (`250m` = un quarto di core). Superare il limite CPU non uccide il container: lo **rallenta** (throttling).
- Memoria in byte (`Mi`, `Gi`). Il valore riportato è il **working set**, quello che il kernel usa per decidere l'OOM. Superare il limite di memoria causa [OOMKilled](guide:oomkilled).
- Confronta sempre l'uso con [request](guide:resource-request) e [limit](guide:resource-limit): un pod al 95% del limite di memoria è a rischio anche se "funziona".

**Eventi** Kubernetes: oggetti `Event` con tipo `Normal` o `Warning`, `reason` e messaggio. Sono conservati per un tempo limitato (di default 1 ora): per incidenti passati non ci si può affidare solo agli eventi.

**Log**: letti tramite l'API del kubelet; vedi [Visualizzare i log](guide:proc-visualizzare-log). Limiti: 5000 righe per richiesta, streaming interrotto dopo 30 minuti o 20000 righe.

**Health**: la pagina [Health](app:/monitoring/health) controlla backend, database, Kubernetes, Podman, spazio libero della cartella dati, configurazione, metrics-server e Prometheus, con stato Healthy, Degraded o Unhealthy.

## Esempio

```bash
# Alternativa da shell
kubectl top nodes
kubectl top pods -n ordini --containers --sort-by=memory
kubectl get events -A --field-selector type=Warning --sort-by=.lastTimestamp
kubectl get apiservice v1beta1.metrics.k8s.io
```

Interpretazione rapida di un pod:

| Metrica | Valore | Request | Limit | Lettura |
|---|---|---|---|---|
| CPU | 480m | 200m | 500m | vicino al limite: probabile throttling |
| Memoria | 490Mi | 256Mi | 512Mi | 96% del limite: rischio OOMKilled |

## Cosa può andare storto

- **metrics-server non installato o non funzionante**: le pagine CPU/Memoria non mostrano dati; Health segnala metrics-server.
- **Prometheus non configurato**: niente storico né rete.
- **Eventi scaduti**: dopo un'ora la causa di un problema notturno non è più negli eventi.
- **Log persi**: dopo la ricreazione del pod i log del vecchio pod non sono più disponibili (salvo il container precedente nello stesso pod).
- Lettura sbagliata: guardare la media del nodo e ignorare il singolo pod vicino al limite.

## Come verificare

- [Monitoraggio → CPU](app:/monitoring/cpu), [Memoria](app:/monitoring/memory), [Storage](app:/monitoring/storage).
- [Monitoraggio → Health](app:/monitoring/health): metrics-server e Prometheus devono essere Healthy se li usi.
- [Monitoraggio → Eventi](app:/monitoring/events) e [Log](app:/monitoring/logs).

## Come risolvere

- Installa o ripara metrics-server (compito dell'amministratore del cluster); verifica con `kubectl get apiservice v1beta1.metrics.k8s.io`.
- Configura l'URL di Prometheus nelle impostazioni per avere storico e rete.
- Per non perdere log ed eventi, usa una soluzione centralizzata (es. stack di logging del cluster); PKM la affianca, non la sostituisce.
- Quando un pod è stabilmente vicino ai limiti, rivedi request e limit invece di aspettare l'incidente.
