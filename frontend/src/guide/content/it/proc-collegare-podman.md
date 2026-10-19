---
title: Collegare PKM a Podman
summary: Attiva il socket API di Podman (rootful o rootless) e configuralo in PKM, consapevole delle implicazioni di sicurezza.
category: procedures
order: 30
keywords: podman, socket, podman.socket, rootful, rootless, libpod, api, sicurezza
related: cos-e-podman, container, proc-installare, proc-diagnosticare-pod, faq
---

## Quando serve

Quando vuoi gestire da PKM i container Podman dell'host (sezione **Container**: Container, Immagini, Registry), durante il passo **Podman** del wizard oppure se in [Health](app:/monitoring/health) Podman risulta **Unhealthy**.

## Prerequisiti

- PKM installato.
- Podman installato sull'host (`podman --version`).
- Aver deciso **quale** Podman gestire:
  - **rootful**: i container avviati da root, socket `/run/podman/podman.sock`;
  - **rootless**: i container di uno specifico utente, socket `/run/user/<uid>/podman/podman.sock`.

> **Attenzione alla sicurezza.** Chi può scrivere sul socket rootful può avviare container privilegiati e montare il filesystem dell'host: l'accesso equivale di fatto a **root sulla macchina**. Dare al gruppo `pkm` l'accesso al socket significa che una compromissione di PKM è una compromissione dell'host. Proteggi PKM di conseguenza (TLS, password robuste, ruoli minimi) oppure preferisci la modalità rootless.

## Procedura

### Opzione A: Podman rootful

1. Abilita il socket API:

   ```bash
   sudo systemctl enable --now podman.socket
   ```

2. Concedi l'accesso al gruppo `pkm` rieseguendo l'installer con l'opzione esplicita (non viene fatto senza consenso proprio per il rischio descritto sopra): `sudo ./install.sh --podman-access` (dal pacchetto di rilascio; l'installazione è idempotente). L'installer aggiunge il drop-in `/etc/systemd/system/podman.socket.d/10-pkm.conf` (`SocketGroup=pkm`, `SocketMode=0660`) e abilita `podman.socket`. Verifica che sia attivo:

   ```bash
   systemctl cat podman.socket
   ls -l /run/podman/podman.sock   # atteso: srw-rw---- root pkm
   ```

   Se hai abilitato il socket dopo l'installazione, ricarica: `sudo systemctl daemon-reload && sudo systemctl restart podman.socket`.

3. In [Impostazioni → Podman](app:/settings/podman) imposta l'URL `unix:///run/podman/podman.sock` (è il valore predefinito), salva e verifica lo stato della connessione.

### Opzione B: Podman rootless

1. Sull'utente proprietario dei container (es. `appuser`) abilita il socket utente e il "linger", così il socket resta attivo anche senza sessione aperta:

   ```bash
   sudo loginctl enable-linger appuser
   sudo -u appuser XDG_RUNTIME_DIR=/run/user/$(id -u appuser) \
     systemctl --user enable --now podman.socket
   ```

2. Il socket sarà `/run/user/<uid>/podman/podman.sock`. Per default è accessibile solo da quell'utente: l'utente `pkm` deve poterlo raggiungere (permessi sulla directory e sul socket). Valuta con attenzione: l'accesso concede pieno controllo sui container di quell'utente, non sull'host.

3. In [Impostazioni → Podman](app:/settings/podman) imposta l'URL `unix:///run/user/<uid>/podman/podman.sock` e verifica la connessione.

## Verifica

- Dal server, con l'identità di PKM:

  ```bash
  sudo -u pkm curl -s --unix-socket /run/podman/podman.sock http://d/v4.0.0/libpod/_ping
  # atteso: OK
  ```

- In [Health](app:/monitoring/health) Podman è **Healthy**.
- [Container](app:/podman/containers) mostra gli stessi container di `sudo podman ps -a` (rootful) o `podman ps -a` eseguito dall'utente (rootless).

## Se qualcosa va storto

- **`permission denied` sul socket**: l'utente `pkm` non è nel gruppo giusto o il drop-in non è applicato. Controlla `ls -l` del socket e `id pkm`.
- **Socket inesistente**: il servizio non è attivo; `systemctl status podman.socket` (o `systemctl --user` per rootless).
- **La lista dei container è vuota ma ne esistono**: probabilmente stai guardando l'istanza sbagliata. Container rootful e rootless sono completamente separati.
- **Il socket rootless sparisce al logout**: manca `loginctl enable-linger`.
- **Vuoi revocare l'accesso**: disattiva Podman in Impostazioni → Podman, elimina `/etc/systemd/system/podman.socket.d/10-pkm.conf`, poi `systemctl daemon-reload && systemctl restart podman.socket` (oppure reinstalla con `--no-podman-access` dopo aver rimosso il file).
