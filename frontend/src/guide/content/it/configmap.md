---
title: ConfigMap
summary: Contiene configurazione non riservata da passare alle applicazioni come variabili o file.
category: config
order: 10
keywords: configmap, configurazione, variabili d'ambiente, envFrom, file di configurazione, immutable
related: secret, volume, pod, deployment, createcontainerconfigerror
---

## In parole semplici

Una **ConfigMap** separa la configurazione dall'immagine del container. Invece di ricostruire l'immagine per cambiare l'URL di un servizio o il livello di log, scrivi questi valori in una ConfigMap e l'applicazione li legge come **variabili d'ambiente** o come **file**.

Le ConfigMap sono pensate per dati **non riservati**. Password, token e chiavi vanno in un [Secret](guide:secret).

## Dettagli tecnici

- `data`: coppie chiave/valore testuali; `binaryData`: valori binari in base64. Dimensione massima complessiva 1 MiB.
- Modi di utilizzo nel Pod:
  - `env[].valueFrom.configMapKeyRef`: una singola chiave come variabile.
  - `envFrom[].configMapRef`: tutte le chiavi come variabili.
  - volume `configMap`: ogni chiave diventa un file nella cartella di mount.
- **Aggiornamenti**: le variabili d'ambiente vengono lette **solo all'avvio** del container; per applicare una modifica bisogna riavviare i Pod (in PKM: [Operazioni → Restart](app:/operations/restart), equivalente a `kubectl rollout restart`). I file montati da volume si aggiornano da soli dopo qualche decina di secondi, ma non se montati con `subPath`, e l'applicazione deve rileggerli.
- `optional: true` permette al Pod di partire anche se la ConfigMap o la chiave non esistono.
- `immutable: true`: impedisce modifiche e riduce il carico sull'API server; per cambiare valori si crea una nuova ConfigMap con un nome diverso.
- È un oggetto di namespace: un Pod può usare solo ConfigMap del proprio namespace.

In PKM: [Configurazione → ConfigMaps](app:/k8s/configmaps). La scheda Relazioni mostra quali Pod e workload la usano.

## Esempio

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: web-config
  namespace: shop
data:
  LOG_LEVEL: info
  API_URL: http://api.shop.svc.cluster.local
  app.properties: |
    cache.ttl=300
    feature.newCheckout=true
---
# uso nel container (estratto)
# envFrom:
#   - configMapRef: { name: web-config }
```

## Cosa può andare storto

- **[CreateContainerConfigError](guide:createcontainerconfigerror)**: il Pod fa riferimento a una ConfigMap o a una chiave che non esiste.
- **Pod bloccato in ContainerCreating**: il volume `configMap` non può essere montato perché l'oggetto manca.
- **Modifica senza effetto**: hai aggiornato la ConfigMap ma i Pod usano ancora i vecchi valori perché non sono stati riavviati.
- **Dati riservati in chiaro**: password inserite per errore in una ConfigMap, visibili a chiunque possa leggere il namespace.
- **Errore di formato** in un file di configurazione: l'applicazione va in [CrashLoopBackOff](guide:crashloopbackoff) al riavvio.

## Come verificare

In PKM apri la ConfigMap per vedere chiavi e valori e, nella scheda Relazioni, i Pod che la utilizzano.

```bash
kubectl -n shop get configmap web-config -o yaml
kubectl -n shop describe pod <pod> | grep -A3 -i configmap
kubectl -n shop exec <pod> -- printenv LOG_LEVEL
```

## Come risolvere

1. Crea la ConfigMap mancante o correggi il nome/la chiave nel workload.
2. Dopo una modifica riavvia il workload dalla pagina [Restart](app:/operations/restart) perché le variabili vengano rilette.
3. Valida le modifiche nella scheda YAML con il dry-run e controlla il diff prima di applicare.
4. Sposta subito eventuali dati riservati in un [Secret](guide:secret) e cambia le credenziali esposte.
