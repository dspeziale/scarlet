# PROGRESS — Podman Kubernetes Manager

Ultimo aggiornamento: 2026-10-19

## Fase corrente

FASE 14 — Final review: implementazione completa, test eseguiti, documentazione in revisione finale.

## Attività completate

| Fase | Stato | Note |
|---|---|---|
| 1 Analisi | ✔ | Repository vuoto (commit `nuovo`); toolchain locale: Python 3.12, Node 24, Docker Desktop. |
| 2 Architettura | ✔ | FastAPI + React/TS; SQLite WAL; integrazioni K8s/Podman separate; ADR in `docs/architecture-decisions/`. |
| 3 Backend | ✔ | Config (file+env+UI), logging JSON con request id, health, API `/api/v1`, DB migrazioni, auth, RBAC, audit, rate limit, header di sicurezza. |
| 4 Kubernetes | ✔ | Layer REST su urllib3 (kubeconfig/in-cluster tramite client ufficiale), 20 kind, operazioni, log + streaming SSE, metriche, eviction. Provider DEMO in memoria. |
| 5 Podman | ✔ | API libpod su socket unix/http: info, container, immagini, registry, log, azioni, pull, stats. |
| 6 Frontend | ✔ | Layout con menu laterale (gruppi persistenti, modalità compatta, mobile), dashboard, tabelle, dialoghi, notifiche, ricerca globale (Ctrl+K), tema chiaro/scuro, IT/EN. |
| 7 Operations | ✔ | Wizard onboarding immagine → wizard deploy (12 step), scale, restart, rollout/rollback con diff, YAML (vista/edit/validazione dry-run/diff/apply), troubleshooting. |
| 8 Monitoring | ✔ | metrics-server (CPU/RAM), Prometheus opzionale con query in whitelist (storico, rete, volumi), storage, health, eventi, contatori restart, alta affidabilità. |
| 9 Guida | ✔ | 57 articoli × 2 lingue, ricerca, link contestuali da ogni pagina e da ogni problema diagnosticato. |
| 10 Security | ✔ | Argon2id, sessioni server-side, CSRF + Origin, RBAC backend, audit con scrubbing, Secret nascosti (reveal admin+audit), SSRF: ispezione registry solo HTTPS. |
| 11 Installer | ✔ | install/uninstall/upgrade/backup/restore.sh, systemd hardening, timer backup, tarball offline con wheels, Containerfile + Quadlet. |
| 12 Test | ✔ | vedi sotto. |
| 13 Hardening | ✔ | vedi "Problemi trovati e risolti". |
| 14 Final review | in corso | documentazione finale e report. |

## Test eseguiti (risultati reali)

- **Backend pytest**: 262 passed, 7 skipped (integration), coverage 97% su `pkm/`; ruff pulito.
- **Integrazione reale** (kind v0.27 / Kubernetes 1.32 e Podman 5 in container): 7/7 passati — lettura di tutti i kind, deploy/scale/restart/rollback/pause/resume, log + stream, diagnosi ImagePullBackOff reale, cordon/drain plan, Secret masking, CronJob; Podman pull/start/stop/restart/remove/log/immagini.
- **Frontend vitest**: 26/26 (wizard deploy/onboarding, setup wizard, utenti, health, impostazioni, logica di validazione).
- **End-to-end Playwright** (browser reale + backend reale in DEMO): 14/14 — modalità DEMO evidente, dashboard → dettaglio, menu persistente, Centro Operativo + "segna come gestito", diagnosi ImagePullBackOff → guida, onboarding immagine → deploy wizard → deploy, scale-to-zero con conferma digitata, YAML validate + diff, log viewer, ricerca globale, guida contestuale, cambio lingua, RBAC viewer (UI + 403 dal backend), errore spiegato.
- **Installazione su Oracle Linux 9** (container systemd): vedi risultato nel report finale (`tests/installation/run.sh`).
- **Dipendenze**: pip-audit nessuna vulnerabilità; npm audit (produzione) 0 vulnerabilità.

## Problemi trovati e risolti

1. kubernetes-client 37: il token Bearer non veniva inviato (chiave `BearerToken`) → tutte le chiamate a un cluster reale sarebbero state anonime. Trovato dai test di integrazione con kind, corretto.
2. Timeout di connessione riportati come "API lenta" invece che "non raggiungibile" (Windows/porte chiuse) → codici distinti.
3. Verifica backup: archivi troncati o con path non sicuri causavano errori invece di "verifica fallita".
4. 401 di `/auth/me` prima del login svuotava la cache e bloccava l'app su "Caricamento…".
5. Componenti `lazy()` creati durante il render: con React Router 7 (startTransition) la navigazione non completava. Creati una sola volta a livello di modulo.
6. Script con fine riga CRLF (sviluppo su Windows) → bash su Linux falliva. `.gitattributes` + normalizzazione nella build della release.
7. `check_os` sovrascriveva `VERSION` leggendo `/etc/os-release`.
8. Wheel `uvloop` mancante nel tarball offline (pip valuta i marker sull'host di build) → elenco esplicito + controllo.
9. Advisory npm (js-yaml, react-router) → aggiornati a versioni corrette.
10. SSRF potenziale dall'ispezione registry (HTTP verso localhost, redirect non HTTPS) → solo HTTPS.
11. Wizard di setup salvava come override UI anche i valori di default del file → salva solo le differenze.
12. `/run/podman` creato 0700 root:root: il gruppo `pkm` non raggiungeva il socket → drop-in con `DirectoryMode=0711`.
13. Installer dipendente dal comando `hostname` (assente su installazioni minimali) → fallback `hostnamectl`/`uname`/`ip`.
14. `upgrade.sh`: dopo un upgrade fallito la retention poteva eliminare la release precedente → release fallita rimossa al
    rollback, release di provenienza sempre conservata.
15. Backup senza certificati TLS e kubeconfig (disaster recovery incompleto) → inclusi e ripristinati con `--with-config`.

## Decisioni importanti

Vedi `docs/architecture-decisions/` (ADR-001 … ADR-011): stack, SQLite solo per stato applicativo, REST diretto verso Kubernetes senza discovery, Podman come layer separato, diagnostica a funzioni pure con controlli derivati dai dati, installazione nativa systemd con wheels offline (+ modalità Podman/Quadlet), restore solo da CLI a servizio fermo, modalità DEMO rifiutata in produzione, guida Markdown integrata nel bundle.
