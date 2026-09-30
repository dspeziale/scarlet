# Onboarding di una nuova applicazione Docker

Standard aziendale per portare un'applicazione sulla piattaforma. Scarlet è l'implementazione di
riferimento: quando un punto non è chiaro, guardare come è fatto qui.

## 1. Checklist

1. [ ] creare il repository GitHub (branch `main` protetto, CODEOWNERS);
2. [ ] aggiungere `Dockerfile` conforme (§2);
3. [ ] aggiungere gli endpoint `/health`, `/ready`, `/version` (§2);
4. [ ] aggiungere `deploy/` con compose e configurazioni per ambiente (§3);
5. [ ] aggiungere i workflow (`ci.yml`, `deploy.yml`, `promote-production.yml`, `rollback.yml`,
       `release-tag.yml`, `registry-cleanup.yml`) copiandoli da Scarlet e adattando lint/test (§4);
6. [ ] configurare gli Environments GitHub `development` e `production` (GITHUB_ACTIONS.md §3);
7. [ ] preparare i server (INSTALLATION.md) o riusare quelli esistenti: `install-app.sh <nome> ...`;
8. [ ] primo deployment in development dalla CI, poi promozione in produzione;
9. [ ] gestione ordinaria con `appctl --app <nome>`.

## 2. Contratto dell'applicazione

| Elemento | Requisito | Perché |
|----------|-----------|--------|
| nome | `[a-z][a-z0-9-]{1,31}`, uguale per repository, immagine, directory `/opt/apps/<nome>`, project compose | coerenza in tutti gli strumenti |
| `Dockerfile` | multi-stage; base minimale scelta per lo stack (Debian slim di default; Alpine solo se le dipendenze lo permettono; distroless per binari statici); versioni fissate; utente non-root con uid fisso; `HEALTHCHECK`; label OCI (`version`, `revision`, `created`, `source`); `COPY deploy /deploy`; nessun secret | sicurezza, tracciabilità, bundle nell'immagine |
| build args | `APP_VERSION`, `APP_COMMIT`, `APP_BUILD_TIME` esportati come env | `/version` e `appctl status` |
| `GET /health` | 200 se il processo è vivo, senza dipendenze esterne | liveness Docker e appctl |
| `GET /ready` | 200 solo se pronta a servire: dipendenze critiche raggiungibili, schema migrato; body con `checks` | health gate del deploy |
| `GET /version` | JSON con `version`, `commit`, `image` (da env `IMAGE`) | risposta a "cosa gira?" |
| configurazione | solo variabili d'ambiente (nessun file dentro l'immagine) | stessa immagine in tutti gli ambienti |
| secrets | letti da env; file `secrets/app.secrets.env` sul server | mai nell'immagine |
| log | stdout/stderr, una riga per evento, JSON preferito; nessun file di log interno | `appctl logs`, rotazione Docker |
| shutdown | gestione di SIGTERM entro `stop_grace_period` | deploy senza richieste troncate |
| migrazioni | comando esplicito eseguibile via `docker compose run --rm app <cmd>` (l'entrypoint deve permettere comandi alternativi) | `MIGRATE_COMMAND` in `app.conf` |
| porta | una sola porta HTTP interna (es. 8000), pubblicata solo su `127.0.0.1:APP_PORT` | proxy sulla rete docker |
| stato | nessuno stato locale nel container (filesystem read-only); dati in DB/volume dichiarati | ricreabile a ogni deploy |

## 3. Directory `deploy/`

Copiare da Scarlet e adattare:

```
deploy/
├── compose.yaml         servizio "app": image ${IMAGE}, env_file config/secrets, porta 127.0.0.1:${APP_PORT},
│                        hardening (user, read_only, cap_drop, no-new-privileges, limiti, log rotation)
├── compose.db.yaml      solo se il DB è containerizzato (valutare prima: DEPLOYMENT.md §4)
├── compose.dev.yaml     override development (rete proxy, limiti)
├── compose.prod.yaml    override production
├── compose.local.yaml   workstation
├── env/development.env  configurazione non sensibile
├── env/production.env
└── secrets.env.example  elenco dei secrets richiesti (senza valori)
```

Il servizio principale si chiama `app` (o si imposta `APP_SERVICE` in `app.conf`); il container è
`<nome>-app`. Rete `proxy` esterna per essere raggiunti da Caddy.

## 4. Pipeline

Copiare `.github/workflows/*` e `.github/dependabot.yml`; adattare nel `ci.yml` solo i job
`lint`, `test`, `security` allo stack (es. `npm ci && npm test`, `npm audit`). I job `build` e
`deploy-development`, e gli altri workflow, restano identici: dipendono solo da `Dockerfile`,
`deploy/`, `platform/ci/remote-deploy.sh` e dagli Environments.

Fino a quando `platform/` vive nel repository di Scarlet, copiare anche `platform/ci/` (script usato
da `deploy.yml`). Quando la piattaforma avrà il suo repository, i workflow riutilizzabili verranno
richiamati con `uses:` (ARCHITECTURE.md §9).

## 5. Server

Sullo stesso server possono convivere più applicazioni (porte `APP_PORT` diverse, siti Caddy
diversi):

```bash
sudo /opt/platform/server/install-app.sh <nome> production ghcr.io/<owner>/<nome> 8081
sudo -u deploy cp /opt/platform/proxy/sites/scarlet.caddy.example /opt/platform/proxy/sites/<nome>.caddy   # adattare
appctl --app <nome> deploy git-<sha12>
appctl --app <nome> doctor
```

`app.conf` è l'unico punto in cui la piattaforma conosce l'applicazione: nome, repository immagine,
file compose, servizio, porta, health, comando di migrazione, policy di deploy (auto-rollback,
release conservate, backup).

## 6. Manifesto di piattaforma per applicazione (riepilogo)

| Campo | Dove |
|-------|------|
| nome | `app.conf: APP_NAME`, nome repository |
| repository | GitHub |
| image | `app.conf: IMAGE_REPOSITORY` |
| environment | `app.conf: APP_ENVIRONMENT`, GitHub Environments |
| porta | `app.conf: APP_PORT`, `deploy/compose.yaml` |
| health endpoint | `/health`, `/ready` (override `HEALTH_URL`, `READY_URL`) |
| compose | `deploy/*.yaml`, `app.conf: COMPOSE_FILES` |
| secrets | `secrets/app.secrets.env`, GitHub Environment secrets |
| deployment policy | `app.conf: AUTO_ROLLBACK, HEALTH_TIMEOUT, KEEP_RELEASES, BACKUP_BEFORE_MIGRATE, MIGRATE_COMMAND` |

## 7. Cosa non fare

* non aggiungere Kubernetes/Swarm "perché prima o poi servirà";
* non usare `latest`;
* non mettere il DB nello stesso compose senza aver valutato backup, persistenza e migrazioni;
* non creare un secondo modo di fare deploy (script ad hoc sul server): tutto passa da `appctl`.
