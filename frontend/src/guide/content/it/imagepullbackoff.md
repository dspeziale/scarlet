---
title: ImagePullBackOff ed ErrImagePull
summary: Il nodo non riesce a scaricare l'immagine del container dal registry.
category: troubleshooting
order: 30
keywords: imagepullbackoff, errimagepull, immagine, registry, pull, imagepullsecrets, tag, autenticazione
related: troubleshooting, container, secret, deployment, proc-diagnosticare-pod, cos-e-podman
---

## In parole semplici

Prima di avviare un container, il nodo deve scaricare la sua immagine dal registry (Docker Hub, Quay, GHCR, un registry aziendale). Se il download fallisce, il container resta fermo con **ErrImagePull**; dopo alcuni tentativi falliti Kubernetes passa a **ImagePullBackOff**, cioè aspetta sempre di più prima di riprovare. Il container non è mai partito, quindi **non ci sono log**: la causa si trova negli eventi.

Le cause più comuni sono: nome o tag scritto male, immagine inesistente, registry privato senza credenziali, nodo che non raggiunge il registry, limiti di download (rate limit).

## Dettagli tecnici

- Il pull è eseguito dal container runtime del nodo (containerd o CRI-O), non dal control plane. Il nodo deve risolvere il DNS del registry e raggiungerlo in HTTPS.
- `ErrImagePull` è il primo fallimento; `ImagePullBackOff` è lo stato di attesa con back-off esponenziale fino a 5 minuti.
- `imagePullPolicy`: `IfNotPresent` (default se il tag non è `latest`), `Always` (default per `latest` o tag assente), `Never`.
- Per i registry privati serve un Secret di tipo `kubernetes.io/dockerconfigjson` referenziato in `spec.imagePullSecrets` del pod o del ServiceAccount. Il Secret deve stare **nello stesso namespace** del pod.
- Messaggi tipici negli eventi:
  - `manifest unknown` / `not found`: tag o immagine inesistente.
  - `unauthorized` / `authentication required` / `pull access denied`: credenziali mancanti o errate.
  - `toomanyrequests`: rate limit del registry.
  - `dial tcp ... i/o timeout` / `no such host`: problema di rete o DNS dal nodo.
  - `x509: certificate signed by unknown authority`: certificato del registry non attendibile per il nodo.

## Esempio

```bash
kubectl describe pod web-5f7c9d8b6-m2kq9 -n shop
# Events:
#   Warning  Failed   kubelet  Failed to pull image "registry.example.com/shop/web:1.4.2":
#            ... unauthorized: authentication required
#   Warning  Failed   kubelet  Error: ErrImagePull
#   Normal   BackOff  kubelet  Back-off pulling image "registry.example.com/shop/web:1.4.2"

kubectl create secret docker-registry regcred -n shop \
  --docker-server=registry.example.com --docker-username=deploy --docker-password='***'
```

```yaml
spec:
  imagePullSecrets:
    - name: regcred
  containers:
    - name: web
      image: registry.example.com/shop/web:1.4.2
```

## Cosa può andare storto

- Il tag esiste in un registry ma non in quello indicato (ad esempio manca il prefisso del registry e si usa Docker Hub).
- Il Secret di pull è stato creato in un altro namespace.
- La password del registry è scaduta o il token è stato revocato.
- Il proxy aziendale blocca il nodo ma non la tua postazione: dal tuo PC il pull funziona, dal nodo no.
- Si usa `latest` con `imagePullPolicy: Always`: ogni riavvio dipende dalla disponibilità del registry.

## Come verificare

1. Nel [Centro Operativo](app:/operations-center) il problema è segnalato come ImagePullBackOff o ErrImagePull.
2. Apri il pod e leggi la scheda **Eventi**: il messaggio di `Failed to pull image` indica il motivo esatto.
3. Nella scheda **YAML** controlla `image` e `imagePullSecrets`.
4. Verifica che il Secret esista in [Configurazione → Secrets](app:/k8s/secrets) nel namespace corretto.
5. Nella scheda del problema premi **Verifica registry**: si apre il wizard [Onboarding immagine](app:/operations/onboarding) con l'immagine già compilata, che controlla dal server PKM formato del nome, raggiungibilità del registry, autenticazione (puoi inserire credenziali usate una sola volta e mai salvate), esistenza del tag e disponibilità per linux/amd64. Nota: il controllo parte dal server PKM, non dai nodi.
6. Da shell, sul nodo (alternativa per amministratori): `sudo crictl pull registry.example.com/shop/web:1.4.2` per riprodurre il problema.

## Come risolvere

1. **Nome o tag errato**: correggi l'immagine dalla pagina [Deploy](app:/operations/deploy) o nel tab **YAML** del Deployment, valida con il dry-run e applica.
2. **Credenziali**: crea o aggiorna il Secret `docker-registry` nel namespace del pod e aggiungilo a `imagePullSecrets`.
3. **Rete/DNS/certificati**: coinvolgi l'amministratore di sistema per proxy, firewall o la CA del registry sui nodi.
4. **Rate limit**: usa un registry mirror interno o credenziali autenticate.
5. Se il problema è comparso con un nuovo rilascio e serve ripristinare subito il servizio, esegui un [rollback](guide:proc-rollback).

Dopo la correzione Kubernetes riprova da solo; per non aspettare il back-off puoi eliminare il pod e lasciare che il controller lo ricrei.
