# Scarlet e la piattaforma Docker interna

Questo repository contiene due cose:

1. **Scarlet**, la prima applicazione aziendale portata in esercizio con Docker: un piccolo
   servizio web che tiene l'inventario dei rilasci (quale versione di quale applicazione gira in
   quale ambiente).
2. **La piattaforma** (`platform/`, `.github/`, `deploy/`, `docs/`): il modo standard con cui
   costruiamo, pubblichiamo, rilasciamo e gestiamo le applicazioni Docker. Scarlet è la prima; le
   prossime seguiranno lo stesso modello (`docs/ONBOARDING_NUOVA_APPLICAZIONE.md`).

## In due minuti, senza sapere cosa sia Docker

* Gli sviluppatori scrivono codice e lo pubblicano su GitHub.
* GitHub, in automatico, controlla il codice, lo impacchetta in una **immagine** (una scatola
  chiusa che contiene l'applicazione e tutto ciò che le serve) e la conserva in un archivio
  (il **registry**). Ogni immagine ha un'etichetta unica e immutabile, ad esempio
  `git-a1b2c3d4e5f6`, che dice esattamente da quale versione del codice proviene.
* La stessa immagine viene installata prima sul server di **sviluppo** e, dopo un'approvazione
  esplicita, sul server di **produzione**. Non viene mai ricostruita in mezzo: ciò che è stato
  provato è ciò che va in produzione.
* Sul server, gli operatori usano un unico comando, `appctl`, per sapere cosa gira, vedere i log,
  riavviare, fare rollback. Non serve conoscere Docker.

```
$ appctl status
Application:  scarlet
Environment:  production
Version:      0.1.0
Image:        ghcr.io/dspeziale/scarlet:git-a1b2c3d4e5f6
Commit:       a1b2c3d4e5f6
Status:       RUNNING
Health:       HEALTHY (ready)
Started:      2026-09-30 08:42:11
Container:    scarlet-app
Deployed by:  github-actions:mario
Deployed at:  2026-09-30 08:42:00
Previous:     git-9f8e7d6c5b4a (target di rollback)
```

## Il ciclo di vita in una figura

```
sviluppatore ─push─▶ GitHub ─▶ CI (lint, test, scansioni) ─▶ immagine git-<sha12> ─▶ registry GHCR
                                                                                        │
                                          server DEVELOPMENT ◀── appctl deploy ◀────────┘
                                                 │ health OK, smoke test
                                          "Promote to production" (approvazione manuale)
                                                 │
                                          server PRODUCTION  ◀── appctl deploy (stessa immagine)
                                                 │ health OK, altrimenti rollback automatico
                                          operatori: appctl status / logs / restart / rollback
```

## Da dove iniziare

| Sono... | Leggo |
|---------|-------|
| un operatore che deve gestire l'applicazione | [docs/OPERATIONS.md](docs/OPERATIONS.md), poi [docs/RUNBOOK.md](docs/RUNBOOK.md) |
| chi deve preparare un server nuovo | [docs/INSTALLATION.md](docs/INSTALLATION.md) |
| uno sviluppatore | [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) e [docs/GITHUB_ACTIONS.md](docs/GITHUB_ACTIONS.md) |
| chi deve capire perché è fatto così | [docs/ARCHITECTURE_ANALYSIS.md](docs/ARCHITECTURE_ANALYSIS.md) e [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| chi deve rilasciare in produzione | [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) e [docs/ROLLBACK.md](docs/ROLLBACK.md) |
| chi deve portare una nuova applicazione sulla piattaforma | [docs/ONBOARDING_NUOVA_APPLICAZIONE.md](docs/ONBOARDING_NUOVA_APPLICAZIONE.md) |

Documentazione completa in [docs/](docs/): architettura, installazione, operazioni, deployment,
rollback, troubleshooting, sicurezza, backup, disaster recovery, sviluppo, GitHub Actions,
secrets, runbook, onboarding, audit finale.

## Struttura del repository

```
src/scarlet/            applicazione (FastAPI)          tests/               test dell'applicazione
migrations/             migrazioni DB (Alembic)         Dockerfile           immagine (multi-stage, non-root)
deploy/                 compose + configurazioni        platform/appctl/     CLI operativa (Python stdlib)
platform/server/        installazione server, sudoers   platform/proxy/      reverse proxy Caddy
platform/ci/            script usati dai workflow       platform/tests/      test di integrazione (Docker reale)
.github/workflows/      CI, deploy, promozione, rollback docs/               documentazione
```

## Comandi rapidi per lo sviluppatore

```bash
make install     # ambiente Python locale
make lint test   # qualità e test
make run         # applicazione + database in locale su http://127.0.0.1:8080
make stop
```

## Stato del progetto

Versione applicazione: vedi `VERSION`. Informazioni mancanti per il go-live (indirizzi dei server,
raggiungibilità dai runner, nomi DNS, certificati, utente tecnico per il registry) sono elencate
in `docs/ARCHITECTURE_ANALYSIS.md` §8 e in `docs/AUDIT_FINALE.md`.
