# Gestione operativa con appctl

`appctl` è l'unico strumento che un operatore usa sul server. Parla in termini applicativi
(versione, stato, health), non in termini Docker (container id, layer, volumi).

## 1. Prerequisiti dell'operatore

* un account personale sul server, membro del gruppo `appops`;
* accesso SSH con chiave.

Non serve (e non è previsto) essere nel gruppo `docker` o avere una shell come `deploy`.
Ogni comando `appctl` viene eseguito come utente `deploy` tramite `sudo` (regola ristretta) e
registrato nell'audit log con il **vostro** nome utente.

## 2. Comandi

| Comando | Cosa fa | Quando usarlo |
|---------|---------|---------------|
| `appctl status` | Stato sintetico: versione, immagine, commit, stato container, health, avvio, chi ha fatto il deploy | sempre, per primo |
| `appctl health` | Verifica a tre livelli: avviata, viva (`/health`), pronta (`/ready`) con dipendenze | quando `status` non basta |
| `appctl version` | Versione corrente, digest immagine, commit, chi/quando; confronto con quella in esecuzione | per rispondere a "cosa gira in produzione?" |
| `appctl logs` | Log dell'applicazione (`--follow`, `--since 1h`, `--tail 200`, `--all` per includere il DB) | diagnosi |
| `appctl logs --deploy` | Log dettagliato dell'ultimo deploy/rollback | deploy fallito |
| `appctl logs --audit` | Ultime righe dell'audit log | chi ha fatto cosa |
| `appctl restart` | Riavvia i container (`--recreate` per rileggere config e secrets) | applicazione bloccata, cambio configurazione |
| `appctl stop` / `appctl start` | Ferma / avvia l'applicazione | manutenzione |
| `appctl deploy <tag>` | Installa una versione (`git-<sha12>` o `vX.Y.Z`) con migrazioni, health gate e rollback automatico | rilascio manuale (normalmente lo fa la pipeline) |
| `appctl rollback [tag]` | Torna alla versione precedente (o a un tag) | dopo un rilascio problematico |
| `appctl history` | Storico dei deployment con esito e durata | audit, scelta del tag di rollback |
| `appctl doctor` | Diagnostica completa (Docker, disco, memoria, rete, registry, immagine, health, log, config, certificati, backup) | qualsiasi anomalia |
| `appctl backup` | Backup di database, configurazione, secrets e stato | prima di interventi manuali |
| `appctl restore <file> --yes` | Ripristina un backup del database | disaster recovery |
| `appctl config` | Mostra la configurazione effettiva (`app.conf`) | verifica |

Opzioni globali: `--app <nome>` (se sul server ci sono più applicazioni), `--json` (output per
script), `--app-dir <dir>` (solo test).

Aiuto integrato: `appctl --help`, `appctl deploy --help`.

## 3. Esempi

```
$ appctl health
Application:          scarlet
Started:              yes
Alive (/health):      yes
Ready (/ready):       yes
Docker health:        HEALTHY
Dependency database:  ok
Overall:              HEALTHY
```

```
$ appctl version
CURRENT DEPLOYMENT
Application:  scarlet
Environment:  production
Version:      0.1.0
Commit:       a1b2c3d4e5f6
Image:        ghcr.io/dspeziale/scarlet:git-a1b2c3d4e5f6
Digest:       ghcr.io/dspeziale/scarlet@sha256:...
Deployed by:  github-actions:mario
Deployed at:  2026-09-30 10:32:05
Running now:  0.1.0 commit a1b2c3d4e5f6
Previous:     0.0.9 (git-9f8e7d6c5b4a)
```

```
$ appctl history
Quando               Azione    Tag                Versione  Chi                    Esito    Durata
-------------------  --------  -----------------  --------  ---------------------  -------  ------
2026-09-30 10:31:40  deploy    git-a1b2c3d4e5f6   unknown   github-actions:mario   started  -
2026-09-30 10:32:05  deploy    git-a1b2c3d4e5f6   0.1.0     github-actions:mario   success  25s
```

```
$ appctl logs --since 30m --tail 100
$ appctl logs --follow
$ appctl logs --all --tail 50        # anche il database
```

## 4. Exit code

Ogni comando termina con un codice che descrive l'esito. La pipeline e gli script li usano.

| Exit | Significato | Cosa fare |
|------|-------------|-----------|
| 0 | operazione riuscita | - |
| 1 | errore generico | leggere il messaggio; `appctl doctor` |
| 2 | uso errato o configurazione non valida (app.conf, compose, secrets mancanti) | correggere la configurazione indicata |
| 3 | registry non raggiungibile o immagine inesistente | verificare il tag (`appctl history`, GitHub), la rete verso il registry, il login (`appctl doctor`) |
| 4 | deploy fallito, **rollback automatico riuscito**: la versione precedente è attiva e sana | analizzare `appctl logs --deploy`; l'applicazione funziona |
| 5 | un'altra operazione appctl è in corso (lock) | attendere; se il lock è orfano vedere TROUBLESHOOTING |
| 6 | Docker non disponibile | `systemctl status docker` (root), RUNBOOK "Server riavviato" |
| 7 | deploy fallito **e** rollback fallito: applicazione non disponibile | RUNBOOK "Deployment fallito" (priorità massima) |
| 8 | migrazione database fallita: la versione precedente è ancora in esecuzione | analizzare `appctl logs --deploy`; coinvolgere lo sviluppatore |
| 9 | applicazione non sana (`appctl health`, `start`, `restart`) | `appctl logs --tail 200`, RUNBOOK "L'applicazione non risponde" |

## 5. Cosa succede durante un deploy

1. lock esclusivo (un solo deploy per volta sul server);
2. pull dell'immagine dal registry (idempotente);
3. estrazione del bundle compose dall'immagine in `releases/<tag>/`;
4. validazione della configurazione compose;
5. se il tag è già attivo e sano: fine (idempotente);
6. avvio del database (se containerizzato), backup pre-migrazione (produzione), migrazioni;
7. `compose up`: i container dell'applicazione vengono ricreati con la nuova immagine
   (**pochi secondi di indisponibilità**, vedi DEPLOYMENT.md);
8. health gate: container `running` + healthy, `/health` e `/ready` OK entro `HEALTH_TIMEOUT`;
9. successo: aggiornamento di `current.json`/`previous.json`, history, audit, symlink `current`,
   pulizia delle release più vecchie di `KEEP_RELEASES`;
10. fallimento: diagnostica nel log di deploy, rollback automatico alla versione precedente.

## 6. Dove sono le cose sul server

| Cosa | Dove |
|------|------|
| manifest applicazione | `/opt/apps/<app>/app.conf` |
| configurazione non sensibile | `/opt/apps/<app>/config/app.env` |
| secrets | `/opt/apps/<app>/secrets/app.secrets.env` (0600, solo `deploy`) |
| release (bundle compose per tag) | `/opt/apps/<app>/releases/<tag>/`, `current` → release attiva |
| stato deployment | `/opt/apps/<app>/state/{current,previous}.json`, `history.jsonl` |
| log di deploy | `/opt/apps/<app>/logs/deploy-<data>-<tag>.log` |
| dati database | `/opt/apps/<app>/data/postgres/` |
| backup | `/opt/apps/<app>/backups/` |
| audit log | `/var/log/apps/<app>/audit.log` (append-only) |
| reverse proxy | `/opt/platform/proxy/` |

## 7. Cambiare la configurazione senza nuovo deploy

1. modificare `config/app.env` (mai i secrets in questo file);
2. `appctl restart --recreate` (i container vengono ricreati e rileggono i file);
3. `appctl health`.

Per i secrets: modificare `secrets/app.secrets.env` come `deploy`/root, poi `appctl restart --recreate`.
Le modifiche a `config/app.env` sul server vanno riportate anche in `deploy/env/<ambiente>.env`
del repository (fonte di riferimento), altrimenti al prossimo server nuovo si perdono.

## 8. Audit

Ogni comando che cambia stato (deploy, rollback, start, stop, restart, backup, restore) scrive una
riga in `/var/log/apps/<app>/audit.log`:

```
2026-09-30 10:32:05 user=mario env=production app=scarlet action=deploy version=git-a1b2c3d4e5f6 result=success detail="versione 0.1.0 commit a1b2c3d4e5f6"
```

Il file ha l'attributo append-only (`chattr +a`): `appctl` può solo aggiungere righe; solo root può
rimuovere l'attributo. Lo storico dei deployment è anche su GitHub (Environments → deployments).

## 9. Cosa NON fare

* non usare `docker` direttamente per fermare, avviare o cancellare i container dell'applicazione:
  lo stato registrato da `appctl` diventerebbe incoerente;
* non modificare i file in `releases/`: sono estratti dall'immagine e vengono sovrascritti;
* non copiare i secrets in chat, ticket o email;
* non eseguire `appctl deploy` in produzione fuori dalla pipeline se non in emergenza documentata
  (RUNBOOK): il deploy manuale salta la verifica "già validato in development".
