# Sviluppo

## 1. Requisiti sulla workstation

* Python 3.12, `make` (su Windows: Git Bash + `make` da MSYS2/choco, oppure eseguire i comandi
  del Makefile a mano), Docker Desktop o Docker Engine con Compose v2;
* accesso al repository GitHub.

## 2. Setup

```bash
git clone https://github.com/dspeziale/scarlet.git && cd scarlet
make install            # crea .venv e installa requirements-dev.txt + il pacchetto in editable
make lint               # ruff check + ruff format --check
make test               # unit test app (SQLite) + appctl
make run                # build immagine locale, db PostgreSQL, migrazioni, app su http://127.0.0.1:8080
make logs               # log locali
make stop
```

`make run` usa `deploy/compose.yaml + compose.db.yaml + compose.local.yaml` con `IMAGE=scarlet:local`
e i file in `.local/` (config e secrets fittizi, ignorati da git). È lo **stesso compose** che gira
sui server, senza la rete `proxy` e con il DB in un volume Docker (bind mount non adatti a
Windows/macOS per PostgreSQL).

Senza Docker (solo API, DB SQLite):

```bash
export SCARLET_DATABASE_URL=sqlite:///./scarlet.db SCARLET_API_TOKEN=dev
.venv/bin/alembic upgrade head
.venv/bin/python -m scarlet
```

## 3. Struttura del codice

```
src/scarlet/
├── __main__.py        entrypoint: server uvicorn, oppure esegue un comando (alembic ...)
├── main.py            FastAPI: middleware access log, /health, /ready, /version, API, pagina HTML
├── config.py          Settings da variabili d'ambiente (prefisso SCARLET_, metadati APP_*)
├── db.py              engine SQLAlchemy, verifica DB e revisione Alembic per /ready
├── models.py          Application, Deployment
├── schemas.py         Pydantic in/out
└── logging_config.py  log JSON su stdout
migrations/            Alembic (env.py legge SCARLET_DATABASE_URL)
tests/app/             pytest (SQLite; test_postgres.py con SCARLET_TEST_DATABASE_URL)
```

Contratto con la piattaforma (vale per ogni applicazione, ONBOARDING §2):

| Requisito | Dove in Scarlet |
|-----------|-----------------|
| `GET /health` liveness senza dipendenze | `main.py` |
| `GET /ready` readiness con dipendenze critiche | `main.py`, `db.check_database` |
| `GET /version` con `version`, `commit`, `image` | `main.py`, valori da `APP_VERSION`, `APP_COMMIT`, `IMAGE` |
| configurazione solo da env | `config.py` |
| log su stdout, JSON | `logging_config.py` |
| SIGTERM gestito | uvicorn (`timeout_graceful_shutdown`) |
| migrazioni esplicite via comando | `python -m scarlet alembic upgrade head` |
| immagine non-root, read-only | `Dockerfile`, `deploy/compose.yaml` |

## 4. Flusso di lavoro con git

```
feature/<descrizione>  →  pull request  →  main  →  deploy automatico in development
                                                  →  (promozione manuale)  →  production
```

* branch `main` protetto: PR obbligatoria, CI verde, review (CODEOWNERS), niente force push;
* commit piccoli con messaggi descrittivi (`feat: ...`, `fix: ...`, `docs: ...`, `ci: ...`);
* Dependabot apre PR settimanali: vanno revisionate e unite come le altre;
* versione: `VERSION` (semver); alzarla nel PR che introduce la modifica rilevante; il tag git
  `vX.Y.Z` si crea dopo il merge (DEPLOYMENT.md §6).

Nessun GitFlow: un solo branch di lunga vita (`main`) è sufficiente perché la promozione in
produzione avviene per **immagine**, non per branch.

## 5. Migrazioni

```bash
.venv/bin/alembic revision -m "aggiunge colonna note" --autogenerate     # con SCARLET_DATABASE_URL
```

* una migrazione per PR, con `downgrade()` funzionante;
* regola expand/contract (DEPLOYMENT.md §3): retro-compatibile con il codice della versione precedente;
* i test `tests/app/conftest.py` applicano le migrazioni reali su SQLite; in CI anche su PostgreSQL
  (`test_postgres.py`: upgrade → downgrade → upgrade).

## 6. Test

| Suite | Comando | Cosa copre |
|-------|---------|------------|
| applicazione | `pytest tests` | health/ready/version, API, validazioni, escaping HTML, migrazioni |
| applicazione su PostgreSQL | `SCARLET_TEST_DATABASE_URL=... pytest tests/app/test_postgres.py` | migrazioni reali, readiness |
| appctl (unit) | `pytest platform/appctl/tests` | deploy, idempotenza, rollback automatico/manuale, crash, immagine mancante, registry non disponibile, porta occupata, migrazione fallita, lock, pruning, backup/restore, doctor, config, CLI |
| script piattaforma | `pytest platform/tests/unit` | SSH non raggiungibile (exit 20), input non validi, gate SSH (allowlist/deny) |
| integrazione Docker | `make integration` (Linux) | scenario end-to-end con Docker reale: deploy, status/logs/restart/stop/start, upgrade, rollback, backup/restore, doctor, unhealthy → rollback, crash loop, immagine rotta (exit 8), immagine mancante, registry fermo, porta occupata, migrazione fallita |

Integrazione su Windows/macOS (Docker-in-Docker):

```bash
docker run --privileged -d --name scarlet-dind -e DOCKER_TLS_CERTDIR= docker:27-dind
docker exec scarlet-dind sh -c 'apk add python3 py3-pip curl bash && pip install --break-system-packages pytest'
docker cp . scarlet-dind:/repo && docker save scarlet:local | docker exec -i scarlet-dind docker load
docker exec scarlet-dind sh -c 'cd /repo && APPCTL_INTEGRATION=1 APPCTL_TEST_IMAGE=scarlet:local python3 -m pytest platform/tests/integration -m integration -v'
docker rm -f scarlet-dind
```

La CI esegue tutte le suite (`ci.yml`), integrazione inclusa, con l'immagine appena costruita.

## 7. Simulare un deploy fallito

* `SCARLET_SIMULATE_UNHEALTHY=true` nell'ambiente del container fa rispondere 503 a `/health` e
  `/ready`: usato dai test di integrazione per costruire l'immagine "bad";
* deploy di un tag inesistente → exit 3;
* `MIGRATE_COMMAND=alembic upgrade revisione-inesistente` → exit 8.

In development lo si può provare davvero: costruire un'immagine di test con `docker build -f - .`
(`FROM ghcr.io/dspeziale/scarlet:git-<sha>` + `ENV SCARLET_SIMULATE_UNHEALTHY=true`), pubblicarla
con un tag di prova e fare `appctl deploy` sul server dev: si osserva il rollback automatico.

## 8. Convenzioni

* ruff (line length 100, regole E/F/W/I/B/UP/S/N/C4/SIM); `make format` prima del commit;
* commenti e documentazione in italiano, identificatori in inglese;
* nessun `print` nell'applicazione: `logging`;
* nessuna dipendenza nuova senza motivazione nel PR (finisce nell'immagine e nelle scansioni).
