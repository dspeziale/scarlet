# Gestione dei secrets

## 1. Principi

* nessun secret nel repository, nel Dockerfile, nell'immagine, nei log, nei YAML versionati;
* secrets di **development** e **production** sempre distinti;
* i workflow di development non vedono mai credenziali di production (GitHub Environments);
* il minimo privilegio per ogni credenziale (token registry solo `read:packages`, chiave SSH con
  forced command, API token per singola applicazione).

## 2. Inventario

| Secret | Dove vive | Chi lo usa | Scopo |
|--------|-----------|------------|-------|
| `GITHUB_TOKEN` | generato da GitHub per ogni run | CI | push su GHCR, API deployments. Nessuna gestione |
| `DEPLOY_SSH_KEY` (privata) | GitHub Environment `development` / `production` | `deploy.yml` | SSH verso il server, come `deploy` con forced command |
| chiave pubblica corrispondente | `/home/deploy/.ssh/authorized_keys` sul server | sshd | |
| `DEPLOY_SSH_HOST_KEY` | GitHub Environment | `deploy.yml` | verifica dell'identità del server (`StrictHostKeyChecking=yes`) |
| `DEPLOY_HOST` | GitHub Environment (secret o variabile) | `deploy.yml` | indirizzo del server |
| `GITHUB_TOKEN` passato ad `appctl --registry-login-stdin` | solo in memoria durante il job di deploy (login e logout automatici) | Docker (pull) sul server | scaricare l'immagine privata **senza** credenziali permanenti sul server |
| token registry permanente (PAT `read:packages` di un utente tecnico) — **opzionale** | `/home/deploy/.docker/config.json` (0600) sul server | operatori che fanno `appctl deploy <tag nuovo>` a mano | pull manuale di tag non ancora presenti sul server |
| `POSTGRES_PASSWORD`, `SCARLET_DATABASE_URL` | `/opt/apps/<app>/secrets/app.secrets.env` (0600, owner deploy) | container app e db | database |
| `SCARLET_API_TOKEN` | idem | container app; client dell'API | `POST /api/deployments` |
| certificato/chiave TLS | `/opt/platform/proxy/certs/` (0600) | Caddy | HTTPS |

Opzioni valutate: GitHub Environments + file protetti (scelta), Vault/secret manager (infrastruttura
aggiuntiva, valutare oltre le 10 applicazioni), Docker secrets (in Compose non-Swarm sono file
montati: equivalenti al file 0600), SOPS nel repository (aggiunge gestione chiavi).

## 3. Sul server

```
/opt/apps/<app>/secrets/app.secrets.env    owner deploy:deploy  0600
```

* generato da `install-app.sh` con valori casuali (`openssl rand -hex`);
* letto dai container tramite `env_file` (mai passato come argomento di comando);
* incluso nei backup (`config-<data>.tar.gz`): i backup vanno protetti come i secrets (BACKUP.md);
* `appctl doctor` segnala permessi diversi da 0600;
* `appctl config` **non** mostra i secrets; i log di deploy non li stampano.

## 4. Su GitHub

Settings → Environments:

| Environment | Secrets | Protection rules |
|-------------|---------|------------------|
| `development` | `DEPLOY_HOST`, `DEPLOY_SSH_KEY`, `DEPLOY_SSH_HOST_KEY` | nessuna (deploy automatico da `main`) |
| `production` | idem, **valori diversi** | required reviewers (≥ 1, meglio 2), deployment branch: `main` |

Variabili (non segrete) per environment: `DEPLOY_USER`, `DEPLOY_PORT`, `DEPLOY_RUNNER`, `APP_URL`, `APP_NAME`.

Nessun PAT personale nei workflow: la CI usa `GITHUB_TOKEN`, anche per il pull sul server: la
pipeline lo passa ad `appctl` su stdin (`--registry-login-stdin`), `appctl` fa `docker login`,
scarica l'immagine e fa `docker logout`. Sul server non resta nessuna credenziale del registry.

Un token permanente sul server (utente tecnico con PAT `read:packages`, `registry-login.sh`) serve
**solo** se gli operatori devono scaricare a mano tag non ancora presenti (deploy manuale di
emergenza). Il rollback ai tag già deployati funziona anche senza registry (`KEEP_RELEASES`).
Alternative: package pubblico (sconsigliato per software interno) o GitHub App.

## 5. Rotazione

| Secret | Procedura | Frequenza consigliata |
|--------|-----------|----------------------|
| chiave SSH pipeline | generare una nuova coppia; `add-deploy-key.sh` con la nuova pubblica; aggiornare `DEPLOY_SSH_KEY`; eseguire un deploy di prova; rimuovere la riga vecchia da `authorized_keys` | 12 mesi, o subito se compromessa |
| host key del server | cambia solo se il server viene reinstallato: aggiornare `DEPLOY_SSH_HOST_KEY` | — |
| token registry | creare un nuovo PAT `read:packages` per l'utente tecnico; `sudo -u deploy registry-login.sh ghcr.io <utente>`; revocare il vecchio; `appctl doctor` | 12 mesi (impostare scadenza sul PAT) |
| `SCARLET_API_TOKEN` | nuovo valore nel file secrets; `appctl restart --recreate`; aggiornare i client | 12 mesi |
| `POSTGRES_PASSWORD` (DB containerizzato) | `appctl backup`; come deploy: `docker compose -p <app> exec db psql -U <user> -c "ALTER USER <user> PASSWORD 'nuova'"`; aggiornare `POSTGRES_PASSWORD` e `SCARLET_DATABASE_URL` nel file secrets; `appctl restart --recreate`; `appctl health` | 12 mesi |
| certificato TLS | SECURITY.md §6 | prima della scadenza (doctor avvisa a 21 giorni) |

Ogni rotazione va registrata (ticket) e, in produzione, eseguita in finestra di manutenzione.

## 6. Se un secret è stato esposto

1. ruotare subito (tabella sopra), a partire da quello esposto;
2. se era nel repository: rimuoverlo dal codice **e** considerarlo compromesso anche se il commit
   viene riscritto (la storia può essere già stata clonata);
3. verificare gli accessi: `journalctl -t appctl-ssh-gate`, `appctl logs --audit`, log GitHub
   (Settings → Audit log), eventi del package GHCR;
4. annotare l'incidente.

## 7. Per gli sviluppatori

* in locale `make run` usa `.local/secrets/app.secrets.env` (ignorato da git) con valori fittizi;
* i test non richiedono secrets reali;
* mai committare `.env`, `*.secrets.env`, chiavi: `.gitignore` li esclude e gitleaks blocca la CI.
