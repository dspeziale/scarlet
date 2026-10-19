---
title: Volume
summary: Spazio su disco montato in un container, temporaneo o persistente.
category: storage
order: 10
keywords: volume, emptydir, hostpath, configmap, secret, volumemounts, storage, disco
related: persistent-volume, persistent-volume-claim, storage-class, configmap, secret, container
---

## In parole semplici

Il filesystem di un container è **usa e getta**: quando il container viene riavviato, tutto ciò che vi è stato scritto sparisce. Un **volume** è una cartella che viene "montata" dentro il container e che sopravvive almeno ai riavvii del container; alcuni tipi sopravvivono anche alla cancellazione del Pod.

Si dichiara il volume a livello di Pod (`spec.volumes`) e lo si monta in uno o più container con `volumeMounts`, indicando il percorso.

## Dettagli tecnici

Tipi più comuni:

| Tipo | Durata | Uso tipico |
|---|---|---|
| `emptyDir` | vita del Pod | cache, file temporanei, scambio tra container |
| `configMap` / `secret` | legato all'oggetto | file di configurazione, certificati |
| `persistentVolumeClaim` | indipendente dal Pod | dati applicativi, database |
| `hostPath` | legato al nodo | agenti di sistema; sconsigliato per le applicazioni |
| `projected` | vita del Pod | combinare token, ConfigMap e Secret |

- `emptyDir` può usare la RAM con `medium: Memory` (conta nel limite di memoria del container) e ha un limite con `sizeLimit`.
- I volumi `configMap` e `secret` vengono aggiornati automaticamente quando l'oggetto cambia (con qualche decina di secondi di ritardo), **tranne** se montati con `subPath`.
- `readOnly: true` nel `volumeMount` impedisce scritture.
- I volumi persistenti si ottengono tramite un [Persistent Volume Claim](guide:persistent-volume-claim), che il cluster lega a un [Persistent Volume](guide:persistent-volume).
- `hostPath` dà accesso al filesystem del nodo: è un rischio di sicurezza e lega il Pod a quel nodo.
- `securityContext.fsGroup` imposta il gruppo proprietario dei file del volume, utile quando il container non gira come root.

## Esempio

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: web
  namespace: shop
spec:
  securityContext:
    fsGroup: 1000
  containers:
    - name: web
      image: registry.example.com/shop/web:1.4.2
      volumeMounts:
        - { name: cache, mountPath: /tmp/cache }
        - { name: config, mountPath: /etc/web, readOnly: true }
        - { name: uploads, mountPath: /data/uploads }
  volumes:
    - name: cache
      emptyDir: { sizeLimit: 500Mi }
    - name: config
      configMap: { name: web-config }
    - name: uploads
      persistentVolumeClaim: { claimName: web-uploads }
```

## Cosa può andare storto

- **Dati persi** perché salvati in `emptyDir` o nel filesystem del container invece che in un PVC.
- **`FailedMount` / `FailedAttachVolume`**: il volume non si monta (PVC non Bound, disco ancora agganciato a un altro nodo, driver CSI assente).
- **Permission denied** nel container: l'utente del processo non ha i permessi sui file del volume.
- **ConfigMap o Secret inesistente**: il Pod resta in `ContainerCreating` con evento di mount fallito.
- **Evizione** del Pod perché un `emptyDir` riempie il disco del nodo (`ephemeral-storage`).

## Come verificare

In Scarlet apri il Pod: la scheda Panoramica elenca i volumi montati, la scheda Eventi mostra `FailedMount` con il motivo, la scheda Relazioni collega PVC, ConfigMap e Secret.

```bash
kubectl -n shop describe pod web | sed -n '/Volumes:/,/QoS/p'
kubectl -n shop get events --field-selector reason=FailedMount
kubectl -n shop exec web -- df -h /data/uploads
```

## Come risolvere

1. Per `FailedMount` leggi il messaggio esatto: nome dell'oggetto mancante o errore del driver.
2. Se il PVC è Pending, vedi [Persistent Volume Claim](guide:persistent-volume-claim).
3. Per problemi di permessi imposta `fsGroup` o `runAsUser` coerenti con l'immagine.
4. Sposta i dati importanti su un PVC; usa `emptyDir` solo per dati ricreabili, con `sizeLimit`.
5. Evita `hostPath` per le applicazioni.
