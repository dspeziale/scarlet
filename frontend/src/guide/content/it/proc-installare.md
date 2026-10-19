---
title: Installare Scarlet su Oracle Linux 9.7
summary: Installa Scarlet su un server Oracle Linux 9.7 x86_64 e completa il primo avvio guidato.
category: procedures
order: 10
keywords: installazione, install.sh, oracle linux, setup, token, systemd, tls, pkm-admin
related: introduzione, proc-collegare-kubernetes, proc-collegare-podman, proc-backup, faq
---

## Quando serve

Quando devi mettere in funzione Scarlet per la prima volta su un server, oppure reinstallarlo su una macchina nuova. Per passare a una versione più recente su un server dove Scarlet è già installato non serve reinstallare: si usa `upgrade.sh` (vedi la sezione finale).

## Prerequisiti

- Server **Oracle Linux 9.7 x86_64** con accesso `sudo`.
- Accesso ai repository AppStream: l'installer installa `python3.12` se manca.
- Il pacchetto di rilascio `pkm-<version>-linux-x86_64.tar.gz`.
- La porta che userai (default **8443/tcp**) raggiungibile dai browser degli operatori. Se `firewalld` è attivo l'installer la apre automaticamente (salvo `--no-firewall`).
- Facoltativo ma consigliato: un kubeconfig dedicato (vedi [Collegare Kubernetes](guide:proc-collegare-kubernetes)) e/o il socket Podman attivo (vedi [Collegare Podman](guide:proc-collegare-podman)). Puoi anche configurarli dopo, dal wizard o da [Impostazioni](app:/settings/system).

## Procedura

1. Copia il pacchetto sul server ed estrailo:

   ```bash
   tar -xzf pkm-<version>-linux-x86_64.tar.gz
   cd pkm-<version>-linux-x86_64
   ```

2. Avvia l'installer. In modalità interattiva ti farà alcune domande:

   ```bash
   sudo ./install.sh
   ```

   Opzioni utili:

   | Opzione | Effetto |
   |---|---|
   | `--port N` | porta di ascolto (default 8443; 8080 con `--no-tls`) |
   | `--bind ADDR` | indirizzo di ascolto (default `0.0.0.0`) |
   | `--no-tls` | disattiva HTTPS (solo dietro un reverse proxy TLS) |
   | `--kubeconfig PATH` | kubeconfig da copiare in `/etc/pkm/kubeconfig` |
   | `--podman-socket URL` | socket API di Podman (default `unix:///run/podman/podman.sock`, `none` per disattivare) |
   | `--podman-access` | concede al gruppo `pkm` l'accesso al socket Podman **rootful** (equivale a root: vedi [Collegare Podman](guide:proc-collegare-podman)) |
   | `--no-firewall` | non apre la porta in firewalld |
   | `--non-interactive` | nessuna domanda, usa i default e le opzioni passate |
   | `--force` | consente sistemi compatibili RHEL 9 diversi da Oracle Linux |

3. L'installer esegue questi passi:
   - crea l'utente di sistema `pkm`;
   - installa il software in `/opt/pkm/releases/<version>` con il link simbolico `/opt/pkm/current`;
   - scrive la configurazione in `/etc/pkm/config.yaml` e le variabili segrete in `/etc/pkm/pkm.env` (permessi `0640 root:pkm`);
   - crea la directory dati `/var/lib/pkm` (database `/var/lib/pkm/pkm.db`, backup in `/var/lib/pkm/backups`);
   - genera un certificato autofirmato in `/etc/pkm/tls/` (se non ne esiste già uno);
   - installa e avvia `pkm.service` e il timer di backup `pkm-backup.timer`;
   - installa il comando di amministrazione `pkm-admin`;
   - apre la porta in firewalld se è attivo;
   - attende che il servizio sia pronto e stampa il riepilogo (`Installation completed.`, URL, servizio, stato, prossimo passo).

4. Al termine, **annota il token di setup** stampato a video. È monouso. Se lo perdi, rigeneralo con:

   ```bash
   sudo pkm-admin setup-token
   ```

5. Se hai usato `--no-firewall` o usi un firewall diverso da firewalld, apri la porta manualmente, ad esempio:

   ```bash
   sudo firewall-cmd --permanent --add-port=8443/tcp
   sudo firewall-cmd --reload
   ```

6. Apri il browser su `https://<host>:8443`. Il certificato è autofirmato, quindi il browser mostrerà un avviso: accettalo solo per il primo accesso e sostituisci il certificato appena possibile.

7. Completa il wizard di setup: **Benvenuto → Verifica sistema → Kubernetes → Podman → Autenticazione → Monitoraggio → Backup → TLS → Riepilogo → Test connessione → Completato**. Nel passo Verifica sistema inserisci il token; nel passo Autenticazione crei il primo utente **Administrator**. I componenti opzionali (Podman, Prometheus) non bloccano il completamento.

8. Sostituisci il certificato autofirmato con uno emesso dalla tua CA: copia certificato e chiave in `/etc/pkm/tls/pkm.crt` e `/etc/pkm/tls/pkm.key` (`0640 root:pkm` per la chiave), poi riavvia: `sudo systemctl restart pkm`. Il passo TLS del wizard mostra lo stato attuale e queste istruzioni.

## Verifica

- Servizio attivo:

  ```bash
  systemctl status pkm
  systemctl list-timers pkm-backup.timer
  sudo pkm-admin check-config
  ```

- Log senza errori: `journalctl -u pkm -n 100` oppure `/var/log/pkm/pkm.log`.
- Nell'app, la pagina [Health](app:/monitoring/health) mostra backend e database **Healthy**; Kubernetes e Podman sono Healthy se li hai configurati.
- In alto compare il badge verde **LIVE** con il contesto del cluster. Il banner a strisce **DEMO** non può comparire in produzione: con `environment: production` il servizio rifiuta `mode: demo` all'avvio.

## Se qualcosa va storto

- **L'installer non trova python3.12**: verifica che il repository AppStream sia abilitato (`dnf repolist`).
- **Il servizio non parte**: leggi `journalctl -u pkm -e` e lancia `sudo pkm-admin check-config`; spesso è un errore di sintassi in `config.yaml` o un permesso sbagliato su kubeconfig o `pkm.env`.
- **Il browser non raggiunge la pagina**: controlla porta e bind (`ss -tlnp | grep 8443`) e il firewall.
- **Token perso o non valido**: `sudo pkm-admin setup-token` (funziona finché non esistono utenti).
- **Password dell'amministratore dimenticata**: `sudo pkm-admin reset-password <utente>`, oppure crea un nuovo amministratore con `sudo pkm-admin create-admin`.
- **Aggiornamenti futuri**: estrai il nuovo pacchetto ed esegui `sudo ./upgrade.sh`. Lo script esegue un backup, installa la nuova release, riavvia (il database viene migrato all'avvio), esegue un controllo di salute e, in caso di errore, torna automaticamente alla release precedente ripristinando il database del backup.
- **Disinstallazione**: `sudo /opt/pkm/current/scripts/uninstall.sh` rimuove il software ma conserva configurazione, dati e backup; con `--purge` cancella anche dati e configurazione. Fai prima un [backup](guide:proc-backup).
