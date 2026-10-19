---
title: Cos'è Podman
summary: Il motore di container senza demone di Oracle Linux, diverso da Kubernetes, con modalità rootful e rootless e un socket API.
category: intro
order: 30
keywords: podman, container, rootless, rootful, socket, libpod, api, systemd
related: container, cos-e-kubernetes, proc-collegare-podman, introduzione
---

## In parole semplici

Podman è un programma che **esegue container su una singola macchina**. È lo strumento standard per i container su Oracle Linux e RHEL, compatibile con i comandi di Docker (`podman run`, `podman ps`, `podman images`...).

La differenza con Kubernetes è di scala e di responsabilità:

| | Podman | Kubernetes |
|---|---|---|
| Ambito | Un host | Un cluster di più nodi |
| Chi decide dove gira il container | Tu, sull'host scelto | Lo scheduler |
| Riavvio automatico | Con `--restart` o unità systemd | Sempre, tramite i controller |
| Repliche, rolling update, Service | No (non nativamente) | Sì |

In Scarlet la sezione **Container** (Container, Immagini, Registry) riguarda Podman; tutte le altre sezioni riguardano Kubernetes.

## Dettagli tecnici

**Senza demone.** Podman non ha un demone centrale sempre attivo come Docker: ogni comando avvia direttamente il container tramite `conmon` e un runtime OCI (`crun` o `runc`). Per permettere a programmi esterni come Scarlet di parlare con Podman esiste però un **servizio API** opzionale, attivato via systemd.

**Rootful e rootless.**

- **Rootful**: i container sono gestiti da root. Lo storage è in `/var/lib/containers/storage`, il socket API è `/run/podman/podman.sock`, attivato da `podman.socket` di sistema.
- **Rootless**: i container appartengono a un utente normale, isolati tramite user namespace. Storage in `~/.local/share/containers/storage`, socket in `/run/user/<uid>/podman/podman.sock`, attivato da `systemctl --user enable --now podman.socket` (serve `loginctl enable-linger <utente>` perché resti attivo senza sessione aperta). Ogni utente vede solo i propri container.

**Il socket API.** Scarlet usa la **libpod REST API** esposta dal socket. Il socket è attivato da systemd (`podman.socket`), che avvia `podman.service` alla prima richiesta.

> **Attenzione sicurezza:** chi può scrivere sul socket rootful può avviare container privilegiati e quindi ottenere di fatto i privilegi di root sull'host. L'installer di Scarlet aggiunge un drop-in con `SocketGroup=pkm` e `SocketMode=0660` per dare accesso al gruppo `pkm`: questo equivale a dare a Scarlet un accesso **equivalente a root**. Proteggi di conseguenza l'host, l'accesso a Scarlet e il ruolo Administrator. Se basta gestire i container di un solo utente, preferisci il socket rootless.

## Esempio

Abilitare il socket rootful e verificarlo (da shell, come root):

```bash
systemctl enable --now podman.socket
ls -l /run/podman/podman.sock
curl --unix-socket /run/podman/podman.sock http://d/v4.0.0/libpod/_ping
```

Comandi equivalenti alle pagine di Scarlet:

```bash
podman ps -a                 # Container
podman images                # Immagini
podman logs --tail 100 web   # log di un container
podman restart web
```

## Cosa può andare storto

- **Socket non attivo o inesistente**: Scarlet mostra Podman come Unhealthy nella pagina [Health](app:/monitoring/health).
- **Permesso negato sul socket**: l'utente `pkm` non appartiene al gruppo giusto o il drop-in non è stato applicato (`systemctl daemon-reload` mancante).
- **Socket rootless sparito**: l'utente non ha il linger abilitato e si è disconnesso.
- **Container rootful e rootless confusi**: un container creato da un utente non compare nel socket di root, e viceversa.

## Come verificare

- [Impostazioni → Podman](app:/settings/podman): percorso del socket configurato e test di connessione.
- [Container](app:/podman/containers): devi vedere l'elenco dei container dell'host.
- Da shell:

```bash
systemctl status podman.socket
systemctl cat podman.socket      # mostra anche il drop-in
sudo -u pkm curl --unix-socket /run/podman/podman.sock http://d/v4.0.0/libpod/_ping
```

## Come risolvere

- Socket non attivo: `systemctl enable --now podman.socket` (rootful) oppure `systemctl --user enable --now podman.socket` per l'utente rootless.
- Permessi: dopo aver modificato il drop-in esegui `systemctl daemon-reload` e `systemctl restart podman.socket`.
- Percorso errato: correggilo in [Impostazioni → Podman](app:/settings/podman).
- Procedura completa: [Collegare Podman](guide:proc-collegare-podman).
