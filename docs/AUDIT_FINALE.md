# Audit finale della soluzione

Data: 2026-09-30. Verifica incrociata tra requisiti (`prompt.txt`), codice, test e documentazione.

## 1. Copertura dei requisiti

| Requisito | Stato | Dove |
|-----------|-------|------|
| Analisi ambiente e documento di analisi | fatto | `docs/ARCHITECTURE_ANALYSIS.md` |
| Architettura target con Mermaid | fatto | `docs/ARCHITECTURE.md` |
| Pipeline: checkout, dipendenze, lint, unit test, integration test, scan dipendenze, build, scan immagine, tag immutabile, push, deploy dev, smoke test, health, report | fatto | `.github/workflows/ci.yml`, `deploy.yml`, `platform/ci/remote-deploy.sh` |
| Tag immutabili (`git-<sha12>`, `vX.Y.Z` alias), mai `latest` | fatto | `ci.yml`, `release-tag.yml` |
| Registry GHCR: autenticazione, naming, retention, access control, scanning, lifecycle | fatto | `docs/GITHUB_ACTIONS.md` §7, `registry-cleanup.yml`, `platform/server/registry-login.sh` |
| Deploy dev via SSH: pull, up, health, smoke | fatto | `deploy.yml`, `appctl deploy` |
| Produzione separata, promozione esplicita, stessa immagine, environments, approvazione, secrets separati, storico, rollback | fatto | `promote-production.yml`, `rollback.yml`, GitHub Environments (configurazione documentata) |
| Strategia di deploy valutata e motivata (recreate + health gate + auto-rollback) | fatto | `docs/DEPLOYMENT.md` §2 |
| CLI operativa: status, start, stop, restart, deploy, rollback, logs, health, version, doctor (+ history, backup, restore, config) | fatto | `platform/appctl/` |
| Web UI | rimandata con motivazione e percorso di evoluzione | `docs/ARCHITECTURE_ANALYSIS.md` A12, `ARCHITECTURE.md` §9 |
| Logging: application, container, deployment, audit, system; `--follow/--since/--tail`; rotazione | fatto | `docs/ARCHITECTURE.md` §8, compose `logging`, `daemon.json` |
| Health: `/health`, `/ready`, livelli distinti, deploy FAILED su health fallita, diagnostica, rollback | fatto | `src/scarlet/main.py`, `ops.wait_healthy` |
| Database: valutazione, backup, persistenza, migrazioni esplicite, rollback schema, compatibilità | fatto | `docs/DEPLOYMENT.md` §3-4, `docs/ROLLBACK.md` §4, `docs/BACKUP.md` |
| Secrets: mai nel repo/immagine/log; GitHub Environments + file 0600; dev/prod distinti | fatto | `docs/SECRETS.md`, gitleaks in CI |
| Sicurezza server: baseline completa | fatto | `platform/server/install-server.sh`, `docs/SECURITY.md` |
| Dockerfile: multi-stage, base minimale, versioni fissate, non-root, .dockerignore, healthcheck, layer/cache | fatto | `Dockerfile` |
| Compose: comune/dev/prod senza duplicazioni, limiti risorse, hardening | fatto | `deploy/` |
| Avvio dopo reboot (restart policy vs systemd): scelto e documentato | fatto | `docs/ARCHITECTURE_ANALYSIS.md` §6, `INSTALLATION.md` §12 |
| Backup: struttura, script, retention, doc, TODO off-site | fatto | `appctl backup`, systemd timer, `docs/BACKUP.md` |
| Rollback di primo livello, senza rebuild, con effetto sulle migrazioni documentato | fatto | `appctl rollback`, `docs/ROLLBACK.md` |
| Audit: chi/quando/cosa/ambiente/versione/esito, non modificabile dalle funzioni operative | fatto | `appctl/audit.py`, `chattr +a` in `install-app.sh` |
| Osservabilità baseline + `appctl doctor` | fatto | `ops.doctor` |
| Workflow separati e comprensibili, environments, protection rules, no PAT | fatto | `.github/workflows/` |
| Branching semplice | fatto | `docs/DEVELOPMENT.md` §4 |
| Deployment metadata (app, env, image, tag, commit, actor, timestamp, esito) | fatto | `state/current.json`, `appctl version` |
| Concorrenza (concurrency groups + lock) | fatto | `deploy.yml`, `state.py` |
| Failure handling per caso (comportamento, exit code, messaggio, log, rollback, procedura) | fatto | `docs/OPERATIONS.md` §4, `GITHUB_ACTIONS.md` §6, `RUNBOOK.md` |
| Idempotenza | fatto e testato | `test_deploy_is_idempotent`, integrazione |
| Security scanning: dipendenze, secrets, immagine, Dependabot; CodeQL valutato | fatto | `ci.yml`, `dependabot.yml`, `SECURITY.md` §5 |
| Test: unit (app, appctl), integrazione (Docker/Compose/script), smoke, failure (unhealthy, immagine inesistente, porta occupata, registry non disponibile, SSH non disponibile, deploy fallito), rollback | fatto | §3 |
| Documentazione richiesta (14 file + README) | fatto | `docs/` |
| Runbook con gli scenari richiesti | fatto | `docs/RUNBOOK.md` |
| Installazione da zero in 16 punti | fatto | `docs/INSTALLATION.md` |
| Struttura server con ownership e permessi | fatto | `docs/ARCHITECTURE.md` §5 |
| Multi-applicazione e standardizzazione (onboarding) | fatto | `docs/ONBOARDING_NUOVA_APPLICAZIONE.md` |
| Modello dei privilegi (operatore → appctl → Docker) | fatto | `docs/SECURITY.md` §1 |
| Reverse proxy e TLS | fatto (segnaposto DNS/certificati) | `platform/proxy/`, `SECURITY.md` §6 |
| Resource limits (CPU, RAM, PID, log) | fatto | `deploy/compose*.yaml` |
| Disaster recovery (perdite, RPO/RTO come ASSUMPTION, procedura) | fatto | `docs/DISASTER_RECOVERY.md` |

## 2. Verifiche eseguite in questa sessione

| Verifica | Esito |
|----------|-------|
| `ruff check` + `ruff format --check` su app, appctl, test | OK |
| `pytest tests` (applicazione, SQLite + migrazioni Alembic reali) | 14 passed (1 skipped: PostgreSQL solo in CI) |
| `pytest platform/appctl/tests` (appctl con Docker finto) | 62 passed |
| `pytest platform/tests/unit` (script SSH e gate) | 21 passed |
| `pip-audit -r requirements.txt --strict` | nessuna vulnerabilità nota |
| `docker build` immagine (`scarlet:local`) | OK, 330 MB, utente 10001, label OCI |
| stack locale con `deploy/compose.yaml + compose.db.yaml + compose.local.yaml` | app HEALTHY, `/ready` con schema `0001`, API 201, hardening verificato via `docker inspect` (read-only, cap_drop ALL, pids 256, mem 512M, log 20m×5) |
| `docker compose config` con override dev/prod e proxy | OK |
| `actionlint` sui workflow | OK |
| `shellcheck` sugli script server/CI | OK |
| test di integrazione con Docker reale (Docker-in-Docker, Linux) | vedi §3 |

## 3. Scenario end-to-end (criteri di accettazione)

| # | Criterio | Verificato da |
|---|----------|---------------|
| 1-5 | push → test → build → scan → push registry | `ci.yml` (validato con actionlint; esecuzione reale richiede il repository su GitHub con GHCR: **da eseguire al primo push**) |
| 6-8 | deploy DEVELOPMENT, HEALTHY, smoke test | `deploy.yml` + `remote-deploy.sh` (unit test del failure path SSH); `appctl deploy` verificato con Docker reale (`test_full_lifecycle`) |
| 9-11 | promozione approvata, stessa immagine, PRODUCTION HEALTHY | `promote-production.yml` (verifica tag/digest/label, deploy dev riuscito); flusso `appctl` identico a dev |
| 12 | `appctl status` mostra versione e commit corretti | integrazione: `status --json` → version, commit, image, deployed_by |
| 13 | `appctl logs` mostra i log | integrazione: `logs --tail 50` |
| 14 | `appctl restart` funziona | integrazione: restart → HEALTHY |
| 15 | deploy fallito simulato | integrazione: immagine unhealthy, immagine che va in crash, immagine inesistente, registry fermo, porta occupata, migrazione fallita |
| 16-17 | rollback e ritorno alla versione precedente | integrazione: rollback automatico (exit 4) e manuale (`appctl rollback`), versione precedente in esecuzione verificata via `/version` |
| 18 | procedura documentata | `docs/` |

Risultato dell'ultima esecuzione dei test di integrazione (Docker-in-Docker, immagine
`scarlet:local`): riportato in fondo a questo documento.

## 4. Punti aperti (non risolvibili senza informazioni esterne)

| ID | Tipo | Descrizione | Effetto |
|----|------|-------------|---------|
| B1 | BLOCKER go-live | hostname/IP dei server dev e prod, utente amministrativo | senza server non si esegue INSTALLATION.md |
| B2 | BLOCKER go-live | raggiungibilità dei server dai runner (firewall verso runner GitHub o self-hosted runner) | la pipeline si ferma con exit 20 al passo di deploy |
| R1 | REQUIRED | nomi DNS per ambiente | `sites/<app>.caddy` con segnaposto |
| R2 | REQUIRED | modalità certificati TLS | `tls internal` di default (dev) |
| R3 | REQUIRED | utente tecnico GitHub con PAT `read:packages` | pull da GHCR privato |
| R4 | REQUIRED | approvatori dell'environment `production` | protection rules da configurare |
| R5 | REQUIRED | visibilità del package GHCR | assunto privato |
| C1 | RECOMMENDED | destinazione off-site dei backup | DR limitato a errori applicativi |
| C2 | RECOMMENDED | GitHub Advanced Security (CodeQL, push protection) | non incluso |
| C3 | RECOMMENDED | retention audit log | proposta 90 giorni |
| C4 | RECOMMENDED | canale di notifica esito deploy | solo riepilogo GitHub |
| — | RECOMMENDED | pin per digest dell'immagine base e per SHA delle GitHub Actions | Dependabot li gestisce una volta introdotti |

## 5. Rischi residui accettati

* gruppo `docker` = root per l'utente `deploy` (mitigato: sudoers ristretto, forced command, nessuna password);
* downtime di pochi secondi a ogni deploy (recreate);
* backup solo locale fino a C1;
* la CI non è ancora stata eseguita su GitHub (repository vuoto al momento dell'analisi): il primo
  push su `main` è la prova reale dei passi 1-5 dello scenario; eventuali aggiustamenti (versioni
  delle azioni, permessi del package) sono attesi e documentati in TROUBLESHOOTING.md.

## 6. Prossimi passi consigliati

1. push del repository e prima esecuzione della CI (senza environments il job di deploy fallisce
   con messaggio esplicito sui secrets mancanti: è previsto);
2. fornire B1/B2 e installare il server di development (INSTALLATION.md);
3. configurare l'environment `development` e ripetere la CI: deploy automatico;
4. configurare `production` con approvatori e fare la prima promozione;
5. prova di rollback in produzione in finestra concordata;
6. definire C1 (backup off-site) prima del go-live definitivo.

## 7. Risultato test di integrazione (ultima esecuzione)

Esecuzione del 2026-09-30 in Docker-in-Docker (`docker:27-dind`, Docker 27.5.1, Python 3.12),
immagine `scarlet:local` come base, registry locale `registry:2`:

```
platform/tests/integration/test_deploy_flow.py
  test_full_lifecycle                                        PASSED
  test_unhealthy_deploy_is_rolled_back                       PASSED
  test_crashing_image_detected_quickly                       PASSED
  test_broken_image_fails_before_touching_running_version    PASSED
  test_missing_image                                         PASSED
  test_registry_unavailable                                  PASSED
  test_port_already_in_use                                   PASSED
  test_migration_failure_keeps_old_version                   PASSED
8 passed in 324.97s
```

Bug trovati e corretti grazie a questi test (non rilevabili con i soli unit test):
`docker compose up --no-wait` inesistente; il backup pre-migrazione riattivava la release
corrente facendo ripartire la versione vecchia con esito "success"; `doctor` interrogava in HTTPS
un registry loopback in chiaro.
