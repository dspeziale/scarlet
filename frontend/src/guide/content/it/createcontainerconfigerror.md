---
title: CreateContainerConfigError
summary: Kubernetes non riesce a preparare la configurazione del container, quasi sempre per una ConfigMap o un Secret mancante.
category: troubleshooting
order: 80
keywords: createcontainerconfigerror, configmap mancante, secret mancante, chiave mancante, env, envfrom, runasnonroot
related: configmap, secret, troubleshooting, proc-diagnosticare-pod, container, deployment
---

## In parole semplici

Prima di avviare un container, il kubelet prepara la sua configurazione: variabili d'ambiente, file montati, utente con cui eseguire il processo. Se un pezzo di questa configurazione non si trova, ad esempio una [ConfigMap](guide:configmap) o un [Secret](guide:secret) che non esiste, oppure una chiave specifica che non c'è, il container non può essere creato e resta nello stato **CreateContainerConfigError**.

Il container non è mai partito, quindi **non ci sono log**: la spiegazione è negli eventi del pod. La buona notizia è che, appena la risorsa mancante viene creata, Kubernetes riprova da solo.

## Dettagli tecnici

- Lo stato è `state.waiting.reason: CreateContainerConfigError` e il messaggio indica la causa. Esempi tipici:
  - `configmap "app-config" not found`
  - `secret "db-credentials" not found`
  - `couldn't find key DB_PASSWORD in Secret shop/db-credentials`
  - `container has runAsNonRoot and image will run as root`
- Riguarda i riferimenti usati da `env[].valueFrom.configMapKeyRef`, `env[].valueFrom.secretKeyRef` ed `envFrom`. Se il riferimento ha `optional: true`, l'assenza non blocca l'avvio.
- I volumi da ConfigMap/Secret mancanti producono invece un errore di mount (`FailedMount`, `MountVolume.SetUp failed`) e il pod resta in `ContainerCreating`: il sintomo è diverso ma la causa è simile.
- ConfigMap e Secret sono risorse **namespaced**: un pod può riferirsi solo a quelle del proprio namespace.
- Un errore simile, `CreateContainerError`, è prodotto invece dal runtime (ad esempio nome container duplicato o problema con il comando) e richiede di leggere il messaggio specifico.

## Esempio

```bash
kubectl get pod api-7f9c6d8b5-p4jkd -n shop
# NAME                    READY   STATUS                       RESTARTS   AGE
# api-7f9c6d8b5-p4jkd     0/1     CreateContainerConfigError   0          2m

kubectl describe pod api-7f9c6d8b5-p4jkd -n shop | grep -i error
#  Warning  Failed  kubelet  Error: secret "db-credentials" not found

kubectl get secret db-credentials -n shop
```

```yaml
env:
  - name: DB_PASSWORD
    valueFrom:
      secretKeyRef:
        name: db-credentials
        key: password
```

## Cosa può andare storto

- Il Secret esiste ma in un altro namespace (ad esempio creato in `default`).
- Il nome della chiave non coincide (`DB_PASSWORD` invece di `password`): Kubernetes distingue maiuscole e minuscole.
- Il deploy dell'applicazione è stato eseguito prima di creare ConfigMap e Secret.
- Un Secret è stato eliminato o rinominato durante una pulizia: i pod esistenti continuano a funzionare, ma il primo riavvio fallisce.
- L'immagine gira come root mentre il `securityContext` richiede `runAsNonRoot: true`.

## Come verificare

1. Nel [Centro Operativo](app:/operations-center) e nella pagina [Pod](app:/k8s/pods) il pod appare con stato CreateContainerConfigError.
2. Apri il pod: la scheda **Eventi** mostra il messaggio esatto con il nome della risorsa o della chiave mancante.
3. La scheda **Relazioni** mostra ConfigMap e Secret referenziati dal pod e quali risultano mancanti.
4. Verifica l'esistenza della risorsa in [Configurazione → ConfigMaps](app:/k8s/configmaps) o [Configurazione → Secrets](app:/k8s/secrets) nel namespace corretto. I valori dei Secret sono nascosti: per verificare i nomi delle chiavi non serve rivelarli.

## Come risolvere

1. **Risorsa mancante**: crea la ConfigMap o il Secret nel namespace del pod. Per i Secret serve un ruolo con i permessi adeguati.
2. **Chiave mancante**: aggiungi la chiave alla risorsa oppure correggi il nome della chiave nel tab **YAML** del Deployment, validando con il dry-run.
3. **Riferimento opzionale**: se la variabile non è indispensabile, imposta `optional: true`.
4. **runAsNonRoot**: usa un'immagine che giri come utente non root, oppure imposta `runAsUser` con un UID non zero.
5. Il kubelet riprova automaticamente; verifica che il pod passi a `Running` e `Ready`. Se è urgente ripristinare il servizio dopo un rilascio, valuta un [rollback](guide:proc-rollback).
