# Operazioni

## Servizio

```bash
sudo systemctl start pkm
sudo systemctl stop pkm          # arresto graceful (SIGTERM, fino a 20 s per chiudere le richieste, 30 s TimeoutStopSec)
sudo systemctl restart pkm       # necessario dopo modifiche a config.yaml / pkm.env / certificati
systemctl status pkm
journalctl -u pkm -f             # log in tempo reale
journalctl -u pkm --since "1 hour ago" -p warning
```

`pkm.service` riparte automaticamente in caso di crash (`Restart=on-failure`, 5 s, massimo 5 riavvii in 5 minuti).

## Log

- **journald** (`journalctl -u pkm`, `SyslogIdentifier=pkm`): una riga JSON per evento (`ts`, `level`, `component`,
  `message`, `request_id` e campi aggiuntivi). Ogni richiesta API registra metodo, percorso, stato e durata.
- **File** `/var/log/pkm/pkm.log` (sempre JSON): la rotazione è fatta dall'applicazione (`RotatingFileHandler`,
  `logging.max_bytes` 10 MB × `logging.backup_count` 5 file). Non serve logrotate.
- Livello: `logging.level` (DEBUG/INFO/WARNING/ERROR), modificabile a caldo da Impostazioni → Logging.
- Ogni risposta HTTP ha l'header `X-Request-ID`: è lo stesso id mostrato nei "Dettagli tecnici" degli errori della UI
  e presente nel log → `journalctl -u pkm | grep <request-id>`.

## pkm-admin

Il wrapper `/usr/local/bin/pkm-admin` esegue la CLI come utente `pkm` con la configurazione del servizio.

| Comando | Uso |
|---|---|
| `pkm-admin create-admin --username U [--password-stdin]` | crea un Administrator (chiude il wizard di setup) |
| `pkm-admin reset-password U [--password-stdin]` | nuova password, sblocca l'account, chiude le sessioni |
| `pkm-admin unlock U` | sblocca un account bloccato dai tentativi falliti |
| `pkm-admin list-users` | elenco utenti, ruolo, stato, ultimo accesso |
| `pkm-admin setup-token` | rigenera il token del wizard (solo se non esistono utenti) |
| `pkm-admin backup [--scheduled] [--include-manifests]` | crea un backup e applica la retention |
| `pkm-admin verify-backup FILE` | verifica checksum, file e integrità del DB (exit 1 se fallisce) |
| `pkm-admin restore FILE [--with-config] [--yes]` | ripristino (servizio fermo: usare `restore.sh`) |
| `pkm-admin check-config` | valida la configurazione e stampa i valori effettivi (token mascherati) |
| `pkm-admin purge-audit` | elimina le voci di audit oltre la retention |
| `pkm-admin migrate` | applica le migrazioni del database |

Le operazioni della CLI sono registrate nell'audit come utente `cli:<utente sudo>`.

## Utenti e ruoli

Sicurezza → Utenti (solo Administrator): creazione (password temporanea con cambio obbligatorio al primo accesso),
modifica ruolo/stato, reset password, sblocco, eliminazione con conferma digitata. Non è possibile eliminare o
declassare sé stessi né l'ultimo Administrator.

| Ruolo | Può |
|---|---|
| **Viewer** | vedere cluster, risorse, eventi, metriche, Podman (sola lettura). Non vede i log, i valori dei Secret, l'audit, le impostazioni |
| **Operator** | come Viewer + log, deploy di workload (wizard e YAML dei tipi applicativi), scale, restart, rollout/rollback, eliminazione Pod, start/stop/restart container Podman, gestione notifiche, lettura backup e impostazioni |
| **Administrator** | tutto: valori dei Secret (registrato), YAML di qualsiasi tipo gestito, eliminazioni, manutenzione nodi, pull/rimozione immagini, utenti, audit, impostazioni, backup, manutenzione applicativa |

Matrice completa in Sicurezza → Permessi e in [SECURITY.md](SECURITY.md).

## Impostazioni

- **File** `/etc/pkm/config.yaml` (+ override `PKM_<SEZIONE>__<CHIAVE>` in `/etc/pkm/pkm.env`): tutto, richiede `systemctl restart pkm`.
- **UI** (Impostazioni, Administrator): Kubernetes (abilitazione, kubeconfig, contesto, in-cluster, timeout, cache),
  Podman (abilitazione, URL, timeout), Monitoraggio (intervallo, metrics-server, Prometheus URL/timeout/verifica TLS),
  Logging (livello, limiti del visualizzatore log), Backup (retention, export manifest), Audit (retention),
  Autenticazione (sessioni, blocco, lunghezza minima password). Salvate nel database, applicate subito senza riavvio;
  "Ripristina valori del file" le elimina. Bind, porta, TLS, database e modalità restano solo nel file.

## Monitoraggio e notifiche

- **Centro Operativo**: elenco dei problemi in tempo reale; "Ricontrolla" forza una diagnosi; "Segna come gestito"
  sposta la notifica in *gestita* (chi e quando sono visibili a tutti). Le notifiche si risolvono da sole quando il
  problema scompare e si riaprono se ricompare.
- **Monitoraggio → Health**: stato Healthy/Degraded/Unhealthy di backend, database, Kubernetes, Podman, spazio disco
  (Degraded sotto 10 %, Unhealthy sotto 3 % libero), configurazione (es. assenza di TLS in produzione), metrics-server,
  Prometheus, backup (Degraded se l'ultimo backup ha più di 2 giorni o non esiste). I componenti opzionali non rendono
  il sistema Unhealthy.
- Endpoint per monitoraggio esterno (senza autenticazione): `GET /healthz` (processo vivo), `GET /readyz` (database raggiungibile, 503 altrimenti).

## Backup

`pkm-backup.timer` esegue ogni giorno alle 02:30 (± 15 min) `pkm-admin backup --scheduled`:

```bash
systemctl list-timers pkm-backup.timer
journalctl -u pkm-backup
sudo /opt/pkm/current/scripts/backup.sh --copy-to /mnt/backup/pkm     # backup manuale + copia verificata
```

Dettagli, restore e disaster recovery in [BACKUP.md](BACKUP.md).

## Audit

Sicurezza → Audit Log (Administrator): ricerca libera, filtri per utente, azione, esito, namespace, periodo; dettaglio
JSON; export CSV (massimo 500 righe per export). Retention `audit.retention_days` (default 365): la pulizia avviene
automaticamente ogni ora e con `pkm-admin purge-audit`.

## Manutenzione

- **Nodi** (Operazioni → Manutenzione, Administrator): *cordon* (nessun nuovo Pod), *drain* (piano con i Pod da
  spostare, saltati — DaemonSet, mirror — o bloccati — non gestiti, emptyDir —, evizione rispettando i PDB con
  ritentativi, avanzamento live, annullabile, timeout configurabile), *uncordon* al termine. Procedura in Guida → "Manutenzione di un nodo".
- **Applicazione**: housekeeping (sessioni, audit, notifiche risolte), svuotamento cache, ottimizzazione database
  (`integrity_check`, `VACUUM`).

## Gestione di un incidente

1. Centro Operativo: partire dai CRITICAL, leggere *Cosa sta succedendo* e *Rischio*.
2. Diagnosticare: controlli eseguiti e causa più probabile, poi eventi, log (anche dell'esecuzione precedente), YAML.
3. Decidere e agire: rollback, restart, scale, correzione della configurazione — ogni azione mostra conseguenze e rischio prima della conferma.
4. Verificare: la notifica passa a *risolta*; dashboard e Health tornano verdi.
5. Ricostruire la sequenza dall'Audit Log. Procedura completa in Guida → "Gestione degli incidenti".

## Capacità

Monitoraggio → CPU/Memoria mostrano uso reale (metrics-server) e risorse richieste rispetto alle allocabili per nodo;
Alta affidabilità evidenzia applicazioni con replica singola, repliche sullo stesso nodo, senza PDB/probe/limiti.

## Routine di aggiornamento

1. Verificare un backup recente (`pkm-admin verify-backup`).
2. `sudo ./upgrade.sh` dalla nuova release (backup automatico, rollback automatico in caso di errore).
3. Controllare `systemctl status pkm`, Health e la versione nell'intestazione.
4. Le release precedenti restano in `/opt/pkm/releases` (default 2).
