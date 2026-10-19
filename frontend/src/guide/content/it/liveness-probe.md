---
title: Liveness probe
summary: Il controllo che fa riavviare un container bloccato.
category: reliability
order: 50
keywords: liveness, liveness probe, sonda, riavvio, restart, health check, startup probe
related: readiness-probe, crashloopbackoff, container, pod, troubleshooting
---

## In parole semplici

La **liveness probe** chiede periodicamente al container: "sei ancora vivo?". Se la risposta è no per un certo numero di volte consecutive, Kubernetes **uccide il container e lo riavvia**. Serve a recuperare automaticamente situazioni in cui il processo è ancora in esecuzione ma non funziona più (per esempio un deadlock).

Va usata con attenzione: una liveness configurata male fa riavviare continuamente un'applicazione sana.

## Dettagli tecnici

- Si configura per container in `livenessProbe`, con gli stessi meccanismi della readiness: `httpGet`, `tcpSocket`, `exec`, `grpc`.
- Parametri: `initialDelaySeconds`, `periodSeconds` (default 10), `timeoutSeconds` (default 1), `failureThreshold` (default 3), `terminationGracePeriodSeconds` (opzionale, a livello di probe). `successThreshold` deve valere 1.
- Dopo `failureThreshold` fallimenti, il kubelet invia SIGTERM al container, attende il grace period e poi SIGKILL. Il riavvio segue la `restartPolicy` del Pod e incrementa `restartCount`.
- Riavvii ripetuti portano a [CrashLoopBackOff](guide:crashloopbackoff), con attese crescenti fino a 5 minuti.
- Differenza dalla readiness: la readiness **esclude dal traffico**, la liveness **riavvia**. Possono usare endpoint diversi.
- Per avvii lenti usa una **startupProbe**: finché non ha successo, la liveness è sospesa, evitando che il container venga ucciso mentre si sta ancora avviando.
- La liveness non dovrebbe dipendere da servizi esterni (database, API): se il DB cade, riavviare l'applicazione non serve e può peggiorare la situazione.

## Esempio

```yaml
containers:
  - name: api
    image: registry.example.com/shop/api:2.3.1
    livenessProbe:
      httpGet:
        path: /healthz
        port: 8080
      periodSeconds: 15
      timeoutSeconds: 3
      failureThreshold: 4
    startupProbe:
      httpGet:
        path: /healthz
        port: 8080
      periodSeconds: 10
      failureThreshold: 18
```

Con questi valori il container ha fino a 180 secondi per avviarsi; poi viene riavviato se `/healthz` fallisce per circa un minuto.

## Cosa può andare storto

- **Riavvii continui** di un'applicazione sana: `timeoutSeconds` troppo basso, nessuna startupProbe, path errato.
- **Riavvii sotto carico**: l'applicazione risponde lentamente quando è occupata, la probe va in timeout e il riavvio riduce ulteriormente la capacità.
- **Liveness che dipende dal database**: un problema del DB provoca il riavvio di tutte le repliche.
- **Probe identica alla readiness** con soglie aggressive: il Pod viene ucciso invece di essere solo escluso.
- **Nessuna liveness** su un'applicazione che può bloccarsi: il Pod resta Running ma non risponde.

## Come verificare

- Nella pagina [Pod](app:/k8s/pods) controlla la colonna dei riavvii; la scheda **Eventi** mostra `Liveness probe failed` e `Container ... failed liveness probe, will be restarted`.
- Nella scheda **Log** scegli il container e consulta anche i log del container precedente per capire cosa succedeva prima del riavvio.
- Il [Centro Operativo](app:/operations-center) segnala i Pod in CrashLoopBackOff.

```bash
kubectl -n shop describe pod api-5f6d7c9b8-q8w2n
kubectl -n shop logs api-5f6d7c9b8-q8w2n -c api --previous
```

## Come risolvere

1. Verifica path, porta e tempo di risposta dell'endpoint di liveness.
2. Aggiungi una `startupProbe` se il container viene ucciso durante l'avvio.
3. Aumenta `timeoutSeconds` e `failureThreshold` per tollerare picchi di carico.
4. Rendi l'endpoint di liveness indipendente da dipendenze esterne: deve verificare solo che il processo sia in grado di rispondere.
5. Applica le modifiche dalla scheda **YAML** (validazione con dry-run, diff, applica).
