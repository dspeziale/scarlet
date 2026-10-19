---
title: Secret
summary: Conserva dati riservati come password, token e certificati da passare alle applicazioni.
category: config
order: 20
keywords: secret, password, token, certificato, tls, dockerconfigjson, base64, cifratura
related: configmap, volume, ingress, imagepullbackoff, createcontainerconfigerror
---

## In parole semplici

Un **Secret** funziona come una [ConfigMap](guide:configmap), ma è destinato a informazioni **riservate**: password del database, chiavi API, certificati TLS, credenziali per scaricare immagini da un registry privato.

In Scarlet i valori dei Secret sono **nascosti per impostazione predefinita**. Solo un utente con ruolo **Administrator** può rivelarli, e ogni rivelazione viene registrata nell'[Audit Log](app:/security/audit). Il ruolo Viewer non vede mai i valori.

## Dettagli tecnici

- I valori in `data` sono codificati in **base64**: è una codifica, **non una cifratura**. Chiunque possa leggere il Secret tramite API può decodificarlo. `stringData` permette di scrivere i valori in chiaro nel manifest; l'API server li converte in `data`.
- La protezione reale dipende da: permessi RBAC (chi può fare `get`/`list` sui secrets), cifratura a riposo in etcd (`EncryptionConfiguration` sull'API server) e dal fatto che chi può creare Pod in un namespace può montare tutti i Secret di quel namespace.
- Tipi principali:
  - `Opaque`: generico.
  - `kubernetes.io/tls`: chiavi `tls.crt` e `tls.key`, usato dagli [Ingress](guide:ingress).
  - `kubernetes.io/dockerconfigjson`: credenziali di registry, referenziate in `spec.imagePullSecrets` del Pod o del ServiceAccount.
  - `kubernetes.io/service-account-token`: token legacy di un ServiceAccount.
- Uso nel Pod: `env[].valueFrom.secretKeyRef`, `envFrom[].secretRef` o volume `secret` (montato su tmpfs, quindi non scritto sul disco del nodo).
- Le stesse regole di aggiornamento delle ConfigMap: le variabili richiedono un riavvio, i volumi si aggiornano (salvo `subPath`). Limite 1 MiB; supporta `immutable: true`.

In Scarlet: [Configurazione → Secrets](app:/k8s/secrets).

## Esempio

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: db-credentials
  namespace: shop
type: Opaque
stringData:
  DB_USER: shop
  DB_PASSWORD: cambiami-subito
```

Credenziali per un registry privato (alternativa da shell):

```bash
kubectl -n shop create secret docker-registry regcred \
  --docker-server=registry.example.com \
  --docker-username=deploy --docker-password='***'
```

## Cosa può andare storto

- **[CreateContainerConfigError](guide:createcontainerconfigerror)**: il Pod usa un Secret o una chiave inesistente.
- **[ImagePullBackOff](guide:imagepullbackoff)** con "unauthorized": manca l'`imagePullSecret` o le credenziali sono scadute.
- **Certificato TLS non applicato** dall'Ingress: Secret in un altro namespace o di tipo errato.
- **Fuga di credenziali**: Secret salvati in chiaro in repository Git, stampati nei log dell'applicazione o copiati in ConfigMap.
- **Rotazione incompleta**: hai cambiato la password nel Secret ma i Pod usano ancora quella vecchia perché non sono stati riavviati.

## Come verificare

In Scarlet apri il Secret: vedi tipo, chiavi e dimensione dei valori senza rivelarli; la scheda Relazioni mostra i Pod che lo usano.

```bash
kubectl -n shop get secret db-credentials
kubectl -n shop describe secret db-credentials   # mostra chiavi e dimensioni, non i valori
kubectl auth can-i get secrets -n shop --as=system:serviceaccount:shop:default
```

## Come risolvere

1. Crea il Secret mancante o correggi nome e chiave nel workload.
2. Dopo una rotazione delle credenziali riavvia il workload da [Operazioni → Restart](app:/operations/restart).
3. Limita con RBAC chi può leggere i Secret e, in Scarlet, assegna il ruolo Administrator solo a chi deve davvero rivelare i valori.
4. Se un Secret è stato esposto, considera la credenziale compromessa: cambiala alla fonte, poi aggiorna il Secret.
5. Non includere valori reali nei manifest salvati in Git; usa strumenti dedicati (Sealed Secrets, External Secrets) se necessario.
