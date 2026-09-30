# Troubleshooting

Problemi specifici con causa e soluzione. Per le procedure operative complete: RUNBOOK.md.

## appctl

| Sintomo | Causa | Soluzione |
|---------|-------|-----------|
| `ERRORE: nessuna applicazione trovata in /opt/apps` | app non installata o `app.conf` mancante | `install-app.sh` (INSTALLATION.md §6) |
| `piu' applicazioni installate: specificare --app` | più app sul server | `appctl --app scarlet ...` o `export APPCTL_APP=scarlet` |
| `manifest non trovato` / `chiavi obbligatorie mancanti` | `app.conf` incompleto | confrontare con `platform/server/templates/app.conf.*` |
| `Docker non raggiungibile` (exit 6) | daemon fermo o utente senza permessi | root: `systemctl start docker`; l'operatore deve usare `appctl`, non `docker` |
| `un'altra operazione appctl e' in corso` (exit 5) | deploy parallelo, o lock orfano dopo un crash | attendere; **lock orfano**: `cat /opt/apps/<app>/state/.lock` mostra pid/host/ora; se il pid non esiste (`ps -p <pid>`), come deploy: `: > /opt/apps/<app>/state/.lock` |
| `immagine non disponibile nel registry` (exit 3) | tag errato o non ancora pubblicato; package privato senza login | tag da GitHub → CI → riepilogo; `appctl doctor` → Registry; `registry-login.sh` |
| `impossibile scaricare ... connection refused/timeout` (exit 3) | rete/proxy/firewall verso `ghcr.io` | `curl -I https://ghcr.io/v2/` dal server; proxy aziendale → configurare `HTTPS_PROXY` per Docker (`/etc/systemd/system/docker.service.d/proxy.conf`) |
| `il bundle dell'immagine non contiene: compose.prod.yaml` | `COMPOSE_FILES` in `app.conf` cita un file non presente in `deploy/` dell'immagine | allineare `app.conf` o `deploy/` |
| `configurazione compose non valida` (exit 2) | variabile mancante in `app.env`/secrets, YAML errato nel bundle | il messaggio indica il file; `appctl config` |
| `migrazione database fallita` (exit 8) | errore Alembic | `appctl logs --deploy`; sviluppatore |
| deploy lento poi `timeout dopo Ns: /ready -> 503 (database: ...)` | app viva ma DB non pronto/schema | `appctl logs --all`; DB esterno non raggiungibile; migrazioni |
| `container terminato (exit code N)` subito | crash all'avvio | `appctl logs --deploy` (contiene gli ultimi log del container) |
| `ATTENZIONE: audit log non scrivibile` | permessi su `/var/log/apps/<app>/audit.log` | root: `install-app.sh` è idempotente e ripristina permessi/ACL |
| `appctl` chiede la password sudo | utente non in `appops`, o sudoers mancante | `id`; root: `usermod -aG appops <utente>`; `visudo -cf /etc/sudoers.d/appctl` |
| `python3: No module named appctl` | installazione appctl incompleta | root: `install-appctl.sh` |
| `Nota: il container e' stato riavviato N volte da Docker` | crash periodici (memoria, errori) | RUNBOOK "Container in crash loop" |
| `la versione in esecuzione non coincide con quella registrata` | qualcuno ha usato `docker` direttamente, o deploy interrotto | `appctl deploy <tag corrente> --force` riallinea |

## Applicazione

| Sintomo | Causa | Soluzione |
|---------|-------|-----------|
| `/health` 200 ma `/ready` 503 `schema non allineato` | migrazioni non applicate | `appctl deploy <tag> --force` (esegue `MIGRATE_COMMAND`) |
| `/ready` 503 `OperationalError ... connection refused` | DB fermo o URL errato | `appctl logs --service db`; controllare `SCARLET_DATABASE_URL` nei secrets |
| `/health` 503 `simulazione` | `SCARLET_SIMULATE_UNHEALTHY=true` in `app.env` | rimuovere la variabile (serve solo ai test) |
| `POST /api/deployments` 503 `API token non configurato` | `SCARLET_API_TOKEN` vuoto | impostarlo nei secrets, `appctl restart --recreate` |
| `POST` 401 | header `X-API-Key` errato | usare il token del file secrets |
| log non JSON | `SCARLET_LOG_FORMAT=text` (dev locale) | è voluto solo per `make run` |
| `Killed` nei log, riavvii | memoria oltre il limite (`deploy.resources.limits.memory`) | analizzare l'uso (`docker stats` come deploy); alzare il limite in `compose.prod.yaml` con un nuovo rilascio |

## Docker / server

| Sintomo | Causa | Soluzione |
|---------|-------|-----------|
| `Bind for 127.0.0.1:8080 failed: port is already allocated` | porta usata da un altro processo/container | `ss -ltnp \| grep 8080`; cambiare `APP_PORT` in `app.conf` o fermare l'altro processo |
| `network proxy declared as external, but could not be found` | rete non creata | root: `docker network create proxy` (lo fa `install-server.sh`) |
| `no space left on device` | disco pieno | RUNBOOK "Disco pieno" |
| container `db` in loop `data directory has wrong ownership` | `data/postgres` non di uid 999 | root: `chown -R 999:999 /opt/apps/<app>/data/postgres` |
| container `db` `initdb: directory exists but is not empty` | directory dati sporca da un tentativo precedente | valutare; se il DB è nuovo: svuotare la directory come root |
| dopo reboot i container non ripartono | Docker disabilitato, `appctl stop` prima del reboot, o `live-restore` incoerente | `systemctl enable --now docker`; `appctl start` |
| `docker: permission denied while trying to connect to the Docker daemon socket` (operatore) | l'operatore non è nel gruppo docker | corretto così: usare `appctl` |
| orario dei log sbagliato | timezone del container (UTC) | i log JSON sono in UTC con offset; `appctl status` mostra l'ora locale |

## GitHub Actions

| Sintomo | Causa | Soluzione |
|---------|-------|-----------|
| `secrets mancanti nell'environment` | Environment senza `DEPLOY_HOST`/`DEPLOY_SSH_KEY`/`DEPLOY_SSH_HOST_KEY` | GITHUB_ACTIONS.md §3 |
| exit 20 `SSH verso <host> fallito` | rete, chiave, host key, forced command che rifiuta | RUNBOOK "La pipeline non raggiunge il server"; `journalctl -t appctl-ssh-gate` |
| `Host key verification failed` | `DEPLOY_SSH_HOST_KEY` diversa dal server | `ssh-keyscan -t ed25519 <host>` e aggiornare il secret |
| Trivy blocca la build | vulnerabilità HIGH/CRITICAL con fix disponibile | aggiornare la dipendenza/immagine base (Dependabot apre PR); in casi motivati aggiungere `.trivyignore` con scadenza |
| `pip-audit` fallisce | CVE su una dipendenza | aggiornare `requirements.txt` |
| gitleaks fallisce | secret nel repository (anche nella storia) | rimuovere e **ruotare** il secret (SECRETS.md); la storia va riscritta solo con decisione esplicita |
| `nessun deploy in development riuscito per il commit` (promozione) | il tag non è passato da development | eseguire prima il deploy dev (CI su main) o, in emergenza, `skip_development_check` |
| `immagine ... non trovata nel registry` (promozione/release) | tag errato, CI non conclusa | attendere la CI; usare il tag del riepilogo |
| il job production resta "Waiting" | attende l'approvazione | Actions → run → Review deployments |
| `il tag git (...) non coincide con il file VERSION` | tag creato senza aggiornare `VERSION` | aggiornare `VERSION`, merge, poi ricreare il tag |
| `actions/delete-package-versions` fallisce | package non ancora esistente o permessi | dopo la prima pubblicazione; `packages: write` |

## Test

| Sintomo | Causa | Soluzione |
|---------|-------|-----------|
| test di integrazione SKIPPED | non su Linux / `APPCTL_INTEGRATION` non impostato | eseguirli in CI o in Linux (`make integration`); su Windows/macOS via Docker-in-Docker (DEVELOPMENT.md §6) |
| `SCARLET_TEST_DATABASE_URL non impostata` | test PostgreSQL saltato | normale in locale; in CI il service container lo imposta |
