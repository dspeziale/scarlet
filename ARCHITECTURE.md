# Architettura

Scarlet — *Secure Cluster Administration, Runtime & Lifecycle Engineering Tool*.

## Componenti

```text
                      ┌────────────────────────── pkm-server (processo unico, utente pkm) ──────────────────────────┐
Browser ──HTTPS──▶    │ Middleware: request id, security headers/CSP, rate limit, X-PKM-Mode                        │
(React SPA servita    │ API REST /api/v1 (FastAPI) ── deps: sessione, CSRF, RBAC (require(Perm)), Audited          │
 dallo stesso         │   ├─ KubernetesService ── cache TTL 3s ── provider: LiveKubernetes | DemoKubernetes ──────────▶ kube-apiserver
 processo)            │   ├─ PodmanProvider: LivePodman (httpx su unix socket / http) | DemoPodman ──────────────────▶ podman.socket
                      │   ├─ Prometheus (query in whitelist) · metrics.k8s.io                                         │
                      │   ├─ diagnostics.analyze() · relations.build() · manifests.generate()                        │
                      │   ├─ UserService · AuditService · NotificationService · BackupService · RuntimeSettings      │
                      │   └─ OperationManager (thread in background: drain, backup)                                  │
                      │ Monitor asyncio (ogni monitoring.poll_interval_seconds) → notifiche → EventBus → SSE /stream │
                      └────────────────────────────── SQLite WAL /var/lib/pkm/pkm.db ───────────────────────────────┘
pkm-admin (CLI) ─────────────────────────────────────────────────▶ stesso DB (pkm-backup.timer usa `pkm-admin backup`)
```

| Componente | Codice | Note |
|---|---|---|
| Frontend | `frontend/` React 18 + TypeScript + Vite, React Router, TanStack Query, i18next, CodeMirror 6 | build statica servita da FastAPI (`pkm/static` nel pacchetto o `server.static_dir`) |
| Backend | `backend/pkm/` FastAPI su uvicorn, Python 3.12 | endpoint sincroni eseguiti nel threadpool; SSE asincroni |
| Configurazione | `config.py`, `runtime_settings.py` | YAML + env `PKM_<SEZIONE>__<CHIAVE>`; un sottoinsieme modificabile dalla UI salvato nel DB |
| Kubernetes Integration Layer | `k8s/live.py`, `k8s/demo.py`, `k8s/service.py`, `k8s/kinds.py` | REST diretto su percorsi noti, nessuna API discovery |
| Podman Integration Layer | `podman/client.py`, `podman/demo.py` | API libpod `/v4.0.0/libpod/...` |
| Diagnostica | `k8s/diagnostics.py` | funzioni pure su uno snapshot del cluster |
| Relazioni | `k8s/relations.py` | grafo owner/selettori/volumi/config/nodo |
| Wizard deploy / onboarding | `k8s/manifests.py`, `images.py` | generazione manifest + rischi; ispezione immagini via Registry v2 |
| Monitoraggio | `monitoring.py`, `health.py` | metrics-server, Prometheus opzionale, health check |
| Sicurezza | `security/` (`users.py`, `rbac.py`, `passwords.py`, `ratelimit.py`), `api/deps.py` | |
| Audit | `audit.py` | |
| Notifiche e monitor | `notifications.py`, `context.py` | |
| Backup | `backup.py` | |
| Operazioni lunghe | `operations.py` | stato in memoria, polling `/operations/{id}` |
| Stato applicativo | `db.py` | SQLite, migrazioni versionate |

### Kubernetes Integration Layer

- Le credenziali sono caricate dalla libreria ufficiale `kubernetes` (`config.load_kube_config` o
  `load_incluster_config`): certificati client, token, plugin exec/OIDC, refresh del token.
- Le richieste partono da `urllib3.PoolManager` costruito con i parametri TLS della `Configuration` verso percorsi REST
  noti (`KindInfo.collection_path/item_path`), con timeout espliciti (`connect_timeout`, `request_timeout`) e un solo
  retry di connessione (mai riprova delle richieste già inviate).
- Scritture: **server-side apply** (`PATCH application/apply-patch+yaml`, `fieldManager=pkm`, `dryRun=All` per la
  validazione), merge patch per scale/restart/pause, JSON patch per il rollback, Eviction API per il drain (fallback
  `policy/v1beta1`).
- Log: lettura del corpo grezzo; streaming con `follow=true&timestamps=true`, riconnessione con `sinceTime` e
  deduplicazione delle righe dopo un read timeout.
- Errori HTTP/transport mappati su codici stabili (`k8s_unavailable`, `k8s_timeout`, `k8s_auth_failed`,
  `k8s_forbidden`, `k8s_not_found`, `k8s_conflict`, `k8s_invalid`, `k8s_unsupported`, `k8s_not_configured`).
- `KubernetesService`: cache delle list per 3 s (`kubernetes.cache_ttl_seconds`) invalidata a ogni scrittura;
  snapshot paralleli (8 thread) dei tipi necessari a dashboard e diagnostica, tollerante ai 403 per singolo tipo
  (riportati come `partial`).
- `DemoKubernetes` (solo `mode: demo`): store in memoria con scenari realistici e simulazione di scale, restart, rollout, rollback.

### Podman Integration Layer

Separato da Kubernetes: `LivePodman` usa `httpx` con trasporto unix socket (`podman.url: unix:///run/podman/podman.sock`)
o HTTP (solo reti fidate). Supporta info/versione, container (list, inspect, logs con demultiplexing, start/stop/restart,
remove), immagini (list, inspect, pull, remove), registry configurati, statistiche. La UI indica sempre "Runtime: Podman".

### Diagnostica, notifiche e monitor

`diagnostics.analyze(snapshot)` produce `Issue` con gravità, motivo, risorsa, applicazione (top owner), nodo, fatti,
**controlli** (`ok|fail|warn|unknown`, mai inventati: se un dato non è disponibile il controllo è `unknown`),
causa più probabile, azioni e articolo della guida. I Pod con lo stesso problema della stessa applicazione sono raggruppati.
Il monitor (task asyncio) esegue la diagnosi ogni `monitoring.poll_interval_seconds` (default 30), sincronizza la
tabella `notifications` (nuova → aperta, gestita da un utente, risolta automaticamente quando scompare, riaperta se
ricompare), segnala Kubernetes/Podman irraggiungibili e pubblica un evento SSE quando qualcosa cambia; una volta l'ora
esegue la pulizia (sessioni scadute, audit oltre la retention, notifiche risolte da oltre 30 giorni).

## Flusso di una richiesta

1. Il browser invia la richiesta con il cookie di sessione (`__Host-pkm_session` in HTTPS, `pkm_session` in HTTP) e,
   per i metodi non GET, l'header `X-CSRF-Token`.
2. Middleware: request id (`X-Request-ID`), rate limit, header di sicurezza.
3. Dipendenze: sessione valida (idle/absolute), CSRF + controllo `Origin`, permesso RBAC (un rifiuto è registrato
   nell'audit come `access.denied`).
4. L'endpoint chiama il service; le eccezioni `AppError` diventano JSON `{"error": {code, message, params, details, requestId}}`.
5. Le operazioni significative sono registrate nell'audit (successo, fallimento o rifiuto).

## Modello dati (SQLite)

| Tabella | Contenuto |
|---|---|
| `users` | utente, nome, email, hash Argon2id, ruolo, attivo, cambio password obbligatorio, lingua, tentativi falliti, blocco |
| `sessions` | id = SHA-256 del token, utente, token CSRF, creazione, ultima attività, scadenza, IP, user agent |
| `audit_log` | timestamp, utente, azione, kind/nome/namespace, esito, dettaglio JSON (ripulito), IP, user agent, sessione, request id |
| `settings` | impostazioni modificate dalla UI (`sezione.chiave` → JSON) |
| `app_state` | stato interno (hash del token di setup, data di completamento setup) |
| `notifications` | fingerprint, gravità, motivo, sorgente, risorsa, stato, occorrenze, prima/ultima vista, gestione, risoluzione |
| `backups` | archivio, data, dimensione, SHA-256, stato, trigger, contenuto, verifica |
| `schema_version` | versione delle migrazioni |

Lo stato di Kubernetes **non** è duplicato nel database.

## API (`/api/v1`)

| Gruppo | Endpoint principali |
|---|---|
| auth | `POST /auth/login`, `POST /auth/logout`, `GET/PATCH /auth/me`, `POST /auth/change-password`, `GET /auth/sessions`, `POST /auth/sessions/revoke-others` |
| setup | `GET /setup/status`, `POST /setup/verify-token`, `GET /setup/system-check`, `POST /setup/test-kubernetes`, `/test-podman`, `/test-prometheus`, `POST /setup/complete` |
| sistema | `GET /system/info` (pubblico), `GET /system/status`, `GET /health`, `GET /search`, `GET /stream` (SSE), `GET/POST /operations…` |
| cluster | `GET /cluster/overview`, `GET /cluster/issues`, `GET /cluster/ha`, `GET/POST /notifications…` |
| kubernetes | `GET /k8s/kinds`, `GET /k8s/{kind}`, `GET/DELETE /k8s/{kind}/{ns}/{name}`, `…/events`, `…/relations`, `…/diagnose`, `…/metrics`, `POST …/scale`, `…/restart`, `GET /k8s/pods/{ns}/{name}/logs`, `GET …/logs/stream` (SSE), deployments `pause/resume/rollout/rollback`, cronjobs `suspend/trigger`, nodes `cordon/uncordon/drain-plan/drain`, `POST /k8s/validate`, `POST /k8s/apply`, `POST /deploy/preview`, `POST /deploy`, `POST /images/inspect` |
| podman | `GET /podman/info`, `/containers`, `/containers/{id}`, `/containers/{id}/logs`, `POST /containers/{id}/action`, `DELETE /containers/{id}`, `/images`, `/images/{id}/config`, `POST /images/pull`, `DELETE /images/{id}`, `/registries`, `/stats` |
| monitoring | `GET /monitoring/sources`, `/nodes`, `/pods`, `/storage`, `/prometheus/{name}?range=1h|6h|24h|7d` |
| amministrazione | `/users…`, `/rbac/roles`, `/audit`, `/audit/export.csv`, `/audit/{id}`, `GET/PUT/DELETE /settings/{section}`, `/backups…`, `/maintenance/housekeeping`, `/maintenance/cache/clear`, `/maintenance/database/optimize` |

Le risorse cluster-scoped usano `_` come namespace (es. `/k8s/nodes/_/node-01`). Specifica completa:
[docs/api/openapi.json](docs/api/openapi.json) (servita anche su `/api/v1/openapi.json`; Swagger UI `/api/docs` solo in development).
Senza autenticazione: `/healthz`, `/readyz`, `/api/v1/system/info`, `/api/v1/setup/*` (protetti dal token di setup), `/api/v1/auth/login`.

### Server-Sent Events

- `GET /api/v1/stream`: eventi `hello` e `{"type":"notifications","counts":…}` quando cambiano le notifiche; keepalive ogni 20 s.
- `GET /api/v1/k8s/pods/{ns}/{name}/logs/stream?container=&tail=`: righe in batch; eventi `open`, `end` (container
  terminato), `limit` (durata `logs.stream_max_seconds` o righe `logs.stream_max_lines` raggiunte), `error`. Massimo
  `logs.max_concurrent_streams` stream contemporanei.

## Caching e polling

- Backend: cache list 3 s; versione del cluster in cache 30 s; snapshot paralleli; nessuna richiesta per singolo elemento UI.
- Frontend (TanStack Query): `staleTime` 10 s, refresh ogni 30 s solo con la finestra visibile, retry limitati (massimo 2,
  mai sui 4xx, backoff esponenziale), timeout di 45 s per richiesta. Notifiche e problemi si aggiornano subito
  tramite SSE; la riconnessione SSE ha backoff esponenziale e al massimo 8 tentativi.
- Liste filtrate e paginate lato client (50 righe per pagina); audit e notifiche paginati lato server.

## Modello degli errori

Ogni errore ha un `code` (vedi `backend/pkm/errors.py`). Il componente `ErrorPanel` del frontend lo traduce in titolo,
causa probabile e azioni (es. "Verifica connessione Kubernetes", "Riprova"); il messaggio tecnico, lo stato HTTP e il
request id sono in "Dettagli tecnici". Le operazioni distruttive senza conferma restituiscono `428 confirmation_required`
con `params.expected` (il nome da digitare).

## Sicurezza (sintesi)

Autenticazione locale Argon2id, sessioni lato server, CSRF, RBAC nel backend, audit, rate limit, CSP restrittiva,
segreti mai restituiti in chiaro senza permesso esplicito, servizio systemd non privilegiato e confinato. Dettagli in [SECURITY.md](SECURITY.md).

## Topologie di deployment

1. **Nativa (consigliata)**: `install.sh` su Oracle Linux 9.7, `pkm.service` + `pkm-backup.timer`, TLS diretto su 8443.
2. **Container Podman**: immagine da `deploy/podman/Containerfile`, gestita con la Quadlet `deploy/podman/pkm.container`.
3. **Dietro reverse proxy**: `server.host: 127.0.0.1`, TLS terminato dal proxy, `server.trusted_proxies: ["127.0.0.1"]`
   (abilita `X-Forwarded-For` e i cookie `Secure`).

## Layout sul server

| Percorso | Contenuto | Proprietario / permessi |
|---|---|---|
| `/opt/pkm/releases/<versione>/` | venv, scripts, deploy, docs di ogni release | root, 0755 |
| `/opt/pkm/current` | symlink alla release attiva | |
| `/etc/pkm/config.yaml`, `/etc/pkm/pkm.env` | configurazione e override/segreti | root:pkm 0640 |
| `/etc/pkm/tls/pkm.crt`, `pkm.key` | certificato e chiave | 0644 / 0640 root:pkm |
| `/etc/pkm/kubeconfig` | credenziali Kubernetes | root:pkm 0640 |
| `/var/lib/pkm/pkm.db` | database | pkm:pkm |
| `/var/lib/pkm/backups/` | archivi di backup | pkm:pkm 0700 |
| `/var/log/pkm/pkm.log` | log JSON (rotazione applicativa 10 MB × 5) | pkm:pkm |
| `/usr/local/bin/pkm-admin` | wrapper della CLI (esegue come utente pkm) | |
| `/etc/systemd/system/pkm.service`, `pkm-backup.service`, `pkm-backup.timer` | unit systemd | |

## Layout del repository

```text
backend/        pacchetto Python pkm (API, integrazioni, CLI) + tests/
frontend/       SPA React/TS: src/pages, src/components, src/i18n/locales/{it,en}, src/guide/content/{it,en}, e2e/
config/         config.example.yaml, dev-demo.yaml, e2e-demo.yaml
deploy/         systemd/, kubernetes/pkm-rbac.yaml, podman/ (Containerfile, pkm.container)
scripts/        install.sh, upgrade.sh, uninstall.sh, backup.sh, restore.sh, make-kubeconfig.sh, build-release.sh, lib/common.sh
tests/          installation/ (test di installazione su Oracle Linux 9 con systemd)
docs/           architecture-decisions/ (ADR), api/
```
