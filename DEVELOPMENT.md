# Sviluppo

## Struttura del repository

```text
backend/pkm/            applicazione Python
  api/                  router FastAPI (auth, setup, cluster, k8s, podman, monitoring, admin) + deps (sessione, CSRF, RBAC, audit)
  k8s/                  kinds, live (client REST), demo (cluster simulato), service, summarize, diagnostics, relations, manifests, quantity, naming
  podman/               client libpod + demo
  security/             users/sessioni, rbac, passwords, ratelimit
  config.py, db.py, audit.py, notifications.py, backup.py, monitoring.py, health.py, images.py, operations.py,
  runtime_settings.py, context.py, main.py (app factory), cli.py (pkm-server, pkm-admin)
backend/tests/          pytest (unit, API, sicurezza, failure, integrazione)
frontend/src/           pages/, components/, hooks/, api/, auth/, i18n/locales/{it,en}/*.json, guide/content/{it,en}/*.md, styles/
frontend/e2e/           test Playwright
config/                 config.example.yaml, dev-demo.yaml, e2e-demo.yaml
deploy/ scripts/ tests/installation/ docs/
```

## Backend

```bash
python -m venv backend/.venv
backend/.venv/Scripts/pip install -e "backend[dev]"      # Linux: backend/.venv/bin/pip
```

Avvio in DEMO (dati simulati, HTTP su 127.0.0.1:8080, DB in `var/dev/`), dalla radice del repository:

```bash
backend/.venv/Scripts/pkm-server --config config/dev-demo.yaml
```

Al primo avvio il log stampa il token di setup (`setup_token=...`); in alternativa:
`backend/.venv/Scripts/pkm-admin --config config/dev-demo.yaml create-admin --username dev`.
Con `environment: development` la Swagger UI è su `http://127.0.0.1:8080/api/docs`.

Per sviluppare contro un cluster reale: copiare `config/dev-demo.yaml`, impostare `mode: live` e `kubernetes.kubeconfig`.

## Frontend

```bash
cd frontend
npm ci
npm run dev        # http://localhost:5173, proxy di /api verso 127.0.0.1:8080
npm run build      # tsc + vite build in frontend/dist (servita dal backend tramite server.static_dir)
```

## Stile e controlli

```bash
backend/.venv/Scripts/ruff check backend/pkm backend/tests
cd frontend && npx tsc -b
```

Commenti e messaggi d'errore del backend in inglese; testi utente sempre tramite i18n (italiano principale, inglese).

## Test

| Livello | Comando |
|---|---|
| Backend unit/API/sicurezza/failure | `cd backend && .venv/Scripts/python -m pytest` (con copertura: `--cov=pkm --cov-report=term-missing`) |
| Integrazione Kubernetes/Podman reali | vedi [backend/tests/README.md](backend/tests/README.md) (kind + Podman in container, variabili `PKM_IT_KUBECONFIG`, `PKM_IT_PODMAN_URL`) |
| Frontend unit/componenti | `cd frontend && npx vitest run` |
| End-to-end (browser) | `cd frontend && npm run build && npx playwright install chromium && npx playwright test` — avvia il backend in DEMO con `config/e2e-demo.yaml` (porta 8081, DB `var/e2e` ricreato a ogni esecuzione) |
| Installazione su Oracle Linux 9 | `scripts/build-release.sh && tests/installation/run.sh release/pkm-<ver>-linux-x86_64.tar.gz` (Docker o Podman; container privilegiato con systemd: install, idempotenza, backup/restore, upgrade con rollback, uninstall, purge) |

## Release

```bash
scripts/build-release.sh          # release/pkm-<versione>-linux-x86_64.tar.gz + .sha256
```

La versione è in `backend/pkm/__init__.py` (`__version__`); aggiornare anche `CHANGELOG.md`.

## Aggiungere un tipo di risorsa Kubernetes

1. `backend/pkm/k8s/kinds.py`: nuova `KindInfo` (chiave plurale, kind, apiVersion, namespaced, categoria, articolo
   guida, `min_version`, azioni, `workload` se gli Operator possono crearla, `has_logs`).
2. `backend/pkm/k8s/summarize.py`: funzione di riepilogo con `_health` e registrazione in `_SUMMARIZERS`.
3. Eventuale diagnostica in `diagnostics.py`, relazioni in `relations.py`, export in `backup.EXPORT_KINDS`.
4. `deploy/kubernetes/pkm-rbac.yaml`: verbi necessari.
5. Frontend: colonne in `src/pages/k8s/columns.tsx`, `KIND_KEY` in `src/utils/links.ts`, `KIND_GUIDE` in
   `src/guide/index.ts`, voce di menu in `src/components/layout/nav.ts`, traduzioni `k8s:kinds.<Kind>` e `nav:<chiave>` in it/en.
6. Test in `backend/tests/` e aggiornamento della guida.

## Aggiungere una traduzione

I file `frontend/src/i18n/locales/<lingua>/<namespace>.json` sono caricati automaticamente (un file = un namespace,
`t('ns:chiave')`). Ogni chiave deve esistere in `it` e `en`. Per una nuova lingua: creare la cartella con tutti i
namespace e aggiungere il codice a `LANGUAGES` in `src/i18n/index.ts` e ai selettori di lingua (`LANGUAGES` in
`backend/pkm/security/users.py` per la preferenza utente).

## Aggiungere un articolo della guida

File `frontend/src/guide/content/it/<slug>.md` e `.../en/<slug>.md` (stesso slug) con frontmatter:

```markdown
---
title: Deployment
summary: Gestisce copie della tua applicazione e le aggiorna progressivamente.
category: workloads
order: 10
keywords: deployment, replicaset, rolling update
related: replicaset, pod, rolling-update
---
```

Categorie: `intro`, `concepts`, `workloads`, `networking`, `storage`, `config`, `reliability`, `troubleshooting`,
`procedures`, `faq`. Gli articoli di concetto/troubleshooting hanno sei sezioni H2: *In parole semplici*, *Dettagli
tecnici*, *Esempio*, *Cosa può andare storto*, *Come verificare*, *Come risolvere* (EN: *In simple terms*, *Technical
details*, *Example*, *What can go wrong*, *How to verify*, *How to fix*). Le procedure: *Quando serve*, *Prerequisiti*,
*Procedura*, *Verifica*, *Se qualcosa va storto*. Link: `[testo](guide:<slug>)` e `[testo](app:/percorso)`.
Per i collegamenti contestuali aggiornare `KIND_GUIDE`/`REASON_GUIDE` in `src/guide/index.ts`.

## Decisioni architetturali

Le decisioni importanti si registrano in `docs/architecture-decisions/ADR-NNN-titolo.md` (Contesto, Decisione,
Alternative considerate, Conseguenze, Stato). Un ADR superato non si cancella: si marca *Superseded by ADR-NNN*.
