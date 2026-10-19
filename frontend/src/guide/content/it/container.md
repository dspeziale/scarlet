---
title: Container
summary: Un processo isolato avviato da un'immagine, eseguito da Kubernetes dentro un pod o direttamente da Podman.
category: concepts
order: 50
keywords: container, immagine, tag, digest, registry, entrypoint, exit code, podman
related: pod, cos-e-podman, imagepullbackoff, crashloopbackoff, oomkilled, resource-limit
---

## In parole semplici

Un container è un programma che gira isolato dal resto del sistema, con i suoi file, le sue librerie e la sua configurazione, tutto preso da un'**immagine**. L'immagine è il "pacchetto" (ad esempio `nginx:1.27`); il container è quel pacchetto in esecuzione.

In Scarlet i container compaiono in due posti:

- dentro i **pod** Kubernetes (scheda Panoramica del pod, con lo stato di ogni container);
- nella sezione **Container** per gli host Podman ([Container](app:/podman/containers), [Immagini](app:/podman/images), [Registry](app:/podman/registries)), dove un Operator può avviare, fermare e riavviare i container.

## Dettagli tecnici

**Immagine**: un insieme di layer in formato OCI, identificata da `registry/repository:tag` (es. `quay.io/acme/ordini:2.4.1`) oppure, in modo immutabile, da un **digest** `@sha256:...`. Il tag `latest` è mobile: evitarlo in produzione, perché due nodi possono eseguire versioni diverse.

**imagePullPolicy** in Kubernetes: `IfNotPresent` (default con tag specifico), `Always` (default con `latest` o senza tag), `Never`. Le credenziali per registry privati si passano con `imagePullSecrets`.

**Stati di un container in un pod** (`status.containerStatuses[].state`):

- `waiting` con una reason (`ContainerCreating`, `CrashLoopBackOff`, `ImagePullBackOff`, `CreateContainerConfigError`...);
- `running` con l'ora di avvio;
- `terminated` con `exitCode` e `reason` (`Completed`, `Error`, `OOMKilled`).

`lastState` conserva l'ultima terminazione: è il primo posto dove guardare dopo un riavvio. Exit code utili: `0` uscita normale, `1` errore applicativo generico, `137` ucciso con SIGKILL (spesso OOM o liveness fallita), `143` SIGTERM, `126/127` comando non eseguibile o non trovato.

**Isolamento**: namespace Linux (pid, net, mnt, user), cgroup per CPU e memoria ([limit](guide:resource-limit)), SELinux su Oracle Linux. Il filesystem del container è effimero: quello che scrive si perde alla ricreazione, salvo usare [volumi](guide:volume).

## Esempio

```yaml
containers:
  - name: ordini
    image: quay.io/acme/ordini:2.4.1
    imagePullPolicy: IfNotPresent
    ports:
      - containerPort: 8080
    env:
      - name: LOG_LEVEL
        value: info
    resources:
      requests: { cpu: 200m, memory: 256Mi }
      limits: { memory: 512Mi }
```

```bash
# Alternativa da shell (Podman)
podman ps -a --format "{{.Names}} {{.Status}} {{.Image}}"
podman inspect ordini --format "{{.State.ExitCode}} {{.State.OOMKilled}}"
podman logs --tail 200 ordini
```

## Cosa può andare storto

- Immagine inesistente o registry non autorizzato: [ImagePullBackOff](guide:imagepullbackoff).
- Il processo termina subito: [CrashLoopBackOff](guide:crashloopbackoff).
- Supera il limite di memoria: [OOMKilled](guide:oomkilled) (exit code 137).
- Dati scritti nel filesystem del container persi a ogni riavvio.
- Su Podman: container fermo senza politica di riavvio, che non riparte dopo un reboot dell'host.

## Come verificare

- Pod: scheda **Panoramica** (stato, ultimo exit code, riavvii) e scheda **Log** scegliendo il container.
- Podman: [Container](app:/podman/containers) con stato, immagine, porte; dettaglio con log e metriche.
- [Immagini](app:/podman/images) per vedere tag e digest presenti sull'host.

## Come risolvere

- Leggi il `reason` e l'exit code dell'ultima terminazione, poi i log del container precedente.
- Usa tag versionati o digest, mai `latest` in produzione.
- Per dati da conservare monta un volume o un [PersistentVolumeClaim](guide:persistent-volume-claim).
- Su Podman, per container che devono sopravvivere ai reboot, usa una unità systemd (Quadlet) o `--restart=always` con `podman-restart.service` abilitato.
