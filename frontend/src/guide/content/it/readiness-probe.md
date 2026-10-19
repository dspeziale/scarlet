---
title: Readiness probe
summary: Il controllo che dice a Kubernetes quando un Pod è pronto a ricevere traffico.
category: reliability
order: 40
keywords: readiness, readiness probe, sonda, health check, ready, endpoints, startup probe
related: liveness-probe, service, rolling-update, networking, pod
---

## In parole semplici

La **readiness probe** è una domanda che Kubernetes rivolge periodicamente al container: "sei pronto a servire richieste?". Finché la risposta è no, il Pod non riceve traffico dal Service. Il container **non** viene riavviato: semplicemente viene tenuto fuori dal giro finché non torna pronto.

È utile all'avvio (l'applicazione sta ancora caricando) e nei momenti di difficoltà temporanea (una dipendenza non risponde, il Pod è sovraccarico).

## Dettagli tecnici

- Si configura per container in `readinessProbe`. Meccanismi disponibili: `httpGet` (successo con codice 200-399), `tcpSocket` (porta aperta), `exec` (comando con exit code 0), `grpc`.
- Parametri principali: `initialDelaySeconds`, `periodSeconds` (default 10), `timeoutSeconds` (default 1), `successThreshold` (default 1), `failureThreshold` (default 3).
- Il risultato determina la condition `Ready` del container e del Pod. Un Pod non Ready viene spostato tra gli indirizzi **non pronti** dell'EndpointSlice, quindi il Service non gli inoltra traffico.
- Il [rolling update](guide:rolling-update) usa la readiness per decidere quando proseguire: senza probe un Pod è Ready appena il processo parte.
- Senza `readinessProbe` il container è considerato pronto subito dopo l'avvio.
- La **startupProbe** è complementare: finché non ha successo, liveness e readiness non vengono eseguite. Va usata per applicazioni con avvio lento.
- Buona pratica: un endpoint dedicato (es. `/ready`) leggero, che verifica solo ciò che serve davvero per rispondere. Evita di far fallire la readiness per dipendenze condivise da tutte le repliche: andrebbero tutte fuori servizio insieme.

## Esempio

```yaml
containers:
  - name: web
    image: registry.example.com/shop/web:1.5.0
    ports:
      - containerPort: 8080
    readinessProbe:
      httpGet:
        path: /ready
        port: 8080
      initialDelaySeconds: 5
      periodSeconds: 10
      timeoutSeconds: 2
      failureThreshold: 3
    startupProbe:
      httpGet:
        path: /ready
        port: 8080
      periodSeconds: 5
      failureThreshold: 30
```

Il wizard [Deploy](app:/operations/deploy) permette di configurarla al passo **Health check**.

## Cosa può andare storto

- **Pod Running ma 0/1 Ready**: la probe fallisce sempre (path errato, porta sbagliata, timeout troppo basso).
- **Service senza endpoint**: nessun Pod è pronto, gli utenti ricevono errori 503 dall'Ingress.
- **Rollout bloccato**: i nuovi Pod non diventano mai Ready.
- **Probe troppo pesante**: interroga il database a ogni controllo e peggiora il carico.
- **Fallimento a cascata**: tutte le repliche dipendono dallo stesso servizio esterno e diventano non pronte insieme.

## Come verificare

- Nella pagina [Pod](app:/k8s/pods) la colonna Ready mostra i container pronti; la scheda **Eventi** riporta messaggi `Readiness probe failed` con il motivo (es. codice HTTP o timeout).
- La scheda **Diagnostica** del Pod segnala probe che falliscono.
- In [Endpoints](app:/k8s/endpoints) verifica se il Service ha indirizzi pronti.

```bash
kubectl -n shop describe pod web-7d9c8b6f5-x2k4q
kubectl -n shop get endpointslices -l kubernetes.io/service-name=web
kubectl -n shop exec web-7d9c8b6f5-x2k4q -- wget -qO- http://localhost:8080/ready
```

## Come risolvere

1. Verifica che path e porta della probe coincidano con quelli reali dell'applicazione.
2. Aumenta `timeoutSeconds` o `initialDelaySeconds` se l'applicazione è lenta; per avvii molto lunghi usa una `startupProbe`.
3. Se la probe fallisce per una dipendenza esterna, valuta se è corretto escludere il Pod o se basta degradare la funzionalità.
4. Modifica il manifest dalla scheda **YAML**, valida con il dry-run e applica: partirà un rolling update.
