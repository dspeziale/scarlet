# Scarlet

> **S**ecure **C**luster **A**dministration, **R**untime & **L**ifecycle **E**ngineering **T**ool

Console web operativa per **Kubernetes** e **Podman**, installabile su **Oracle Linux 9.7 x86_64** come servizio systemd.
Non è una semplice dashboard: è un centro operativo che risponde subito a *ci sono problemi? quali? quanto gravi?
cosa posso fare?* e che **insegna Kubernetes mentre lo si usa** (ogni pagina spiega i concetti in linguaggio semplice
e rimanda all'articolo della guida integrata).

Metodo: **Capire → Diagnosticare → Decidere → Agire → Verificare**.

Il nome dell'applicazione è configurabile (`app_name` in `config.yaml`).

## Funzionalità (implementate)

- **Dashboard**: stato cluster, nodi pronti/non pronti, Pod attivi e in errore, Deployment degradati, CPU/RAM
  (uso reale da metrics-server e richieste dei Pod), storage (PV/PVC), eventi di warning, restart. Ogni card porta al dettaglio.
- **Centro Operativo**: problemi rilevati automaticamente (CrashLoopBackOff, ImagePullBackOff/ErrImagePull, OOMKilled,
  Pending, CreateContainerConfigError, Pod Failed/Unknown, nodi NotReady o sotto pressione, workload non disponibili o
  degradati, rollout bloccati, Job falliti, PVC Pending/Lost) con gravità CRITICAL/ERROR/WARNING/INFO, rischio,
  **controlli calcolati dai dati reali** (eventi, stati dei container, nodi, StorageClass), causa più probabile e azioni.
- **Risorse Kubernetes**: elenco e dettaglio di Nodes, Namespaces, Events, Pods, Deployments, ReplicaSets,
  StatefulSets, DaemonSets, Jobs, CronJobs, Services, Ingress, Endpoints, PV, PVC, StorageClasses, ConfigMaps, Secrets,
  PodDisruptionBudgets, HorizontalPodAutoscalers. Dettaglio a schede: Panoramica (vista semplice), Relazioni
  (Ingress → Service → Deployment → ReplicaSet → Pod → Node/PVC/ConfigMap/Secret), Pod, Eventi, Log, Metriche, YAML, Diagnostica.
- **YAML**: vista YAML/JSON, modifica con evidenziazione sintassi, lint locale, validazione con **server-side dry-run**,
  diff, applicazione con conferma (server-side apply, field manager `pkm`).
- **Orchestrazione**: scale (scale-to-zero con conferma digitata), rolling restart, pause/resume, cronologia revisioni,
  confronto e rollback, sospensione/esecuzione manuale dei CronJob, cordon/uncordon/drain dei nodi (Eviction API,
  rispetto dei PodDisruptionBudget, avanzamento in tempo reale).
- **Wizard**: *Onboarding immagine* (verifica dell'immagine sul registry tramite Registry v2 API, analisi di porte,
  utente, env, volumi, architetture e rischi) che passa i valori al *Wizard di deploy* in 12 passi (nome, immagine, tag,
  repliche, porta, CPU, RAM, storage, networking, health check, riepilogo con YAML/rischi/dry-run, deploy).
- **Podman** (integrazione separata da Kubernetes): runtime, container (start/stop/restart/remove, log, inspect),
  immagini (pull/remove), registry, statistiche.
- **Monitoraggio**: CPU, memoria, storage, health dei componenti, alta affidabilità (repliche, distribuzione sui nodi,
  PDB, probe, request/limit), eventi, visualizzatore log (tail, live streaming con limiti, pausa, filtro, download).
  Prometheus opzionale (storico, rete, occupazione volumi): se non configurato la UI lo dice, **le metriche non vengono mai inventate**.
- **Sicurezza**: utenti locali (Argon2id), ruoli Administrator/Operator/Viewer verificati nel backend, sessioni lato
  server, CSRF, rate limiting, **audit log** con ricerca/filtri/export CSV.
- **Notifiche** (campanella) con stati aperta/gestita/risolta; aggiornamenti via Server-Sent Events.
- **Ricerca globale** (Ctrl+K o `/`): risorse, eventi, container e immagini Podman, guida.
- **Guida online** integrata IT/EN (57 articoli: concetti, troubleshooting, procedure, FAQ), ricercabile e contestuale.
- **Backup** dell'applicazione (DB + configurazione + export opzionale dei manifest), verifica, timer giornaliero, restore.
- **Installazione**: `install.sh` / `upgrade.sh` (con rollback automatico) / `uninstall.sh` / `backup.sh` / `restore.sh`,
  wizard di prima configurazione, TLS (certificato self-signed generato o certificato della propria CA).
- **i18n**: italiano (principale) e inglese, selezionabili dall'intestazione o dal profilo.
- **DEMO mode** per sviluppo, impossibile da confondere con un cluster reale e rifiutata con `environment: production`.

## Pagine principali

Dashboard · Centro Operativo · Cluster (Panoramica, Nodi, Namespace, Eventi) · Applicazioni · Networking · Storage ·
Configurazione · Container (Podman) · Monitoraggio (CPU, Memoria, Storage, Health, Alta affidabilità, Eventi, Log) ·
Operazioni (Onboarding immagine, Deploy, Scale, Restart, Rollout, Applica YAML, Backup, Manutenzione) ·
Sicurezza (Utenti, Ruoli, Permessi, Audit Log) · Guida · Impostazioni (Sistema, Kubernetes, Podman, Logging, Backup, Autenticazione).
Il menu laterale ha sottomenu espandibili (stato memorizzato nel browser), modalità compatta a sole icone e diventa
un cassetto su schermi piccoli. L'intestazione mostra sempre **LIVE** (con il contesto) o **DEMO**, e le versioni di
Kubernetes, Podman, applicazione e API.

## Quick start

Installazione da release (sul server Oracle Linux 9.7, come root):

```bash
tar xzf pkm-1.0.0-linux-x86_64.tar.gz && cd pkm-1.0.0-linux-x86_64
sudo ./install.sh --kubeconfig /path/to/pkm-kubeconfig
# apri l'URL stampato (https://<host>:8443) e usa il token di setup mostrato a fine installazione
```

Sviluppo in DEMO (Windows/Linux, dalla radice del repository):

```bash
python -m venv backend/.venv && backend/.venv/Scripts/pip install -e "backend[dev]"   # Linux: backend/.venv/bin/pip
cd frontend && npm ci && npm run build && cd ..
backend/.venv/Scripts/pkm-server --config config/dev-demo.yaml     # http://127.0.0.1:8080
```

Dettagli in [DEVELOPMENT.md](DEVELOPMENT.md).

## Architettura in breve

```text
Browser (React/TS)  ──HTTPS, cookie di sessione + X-CSRF-Token──▶  pkm-server (FastAPI, uvicorn)
                                                                     ├─ Auth / RBAC / Audit / Rate limit
                                                                     ├─ Kubernetes Integration Layer ──▶ API server (kubeconfig ServiceAccount pkm)
                                                                     ├─ Podman Integration Layer ──────▶ /run/podman/podman.sock (libpod REST)
                                                                     ├─ Monitoring (metrics-server, Prometheus opzionale)
                                                                     ├─ Diagnostica + monitor notifiche (ogni 30 s)
                                                                     └─ SQLite /var/lib/pkm/pkm.db (solo stato applicativo)
```

Il browser non comunica mai con Kubernetes o Podman. Vedi [ARCHITECTURE.md](ARCHITECTURE.md).

## Versioni supportate

| Componente | Versione |
|---|---|
| Sistema operativo | Oracle Linux 9.7 x86_64 con systemd (altre RHEL 9 compatibili solo con `install.sh --force`) |
| Python | 3.12 da AppStream (`python3.12`), minimo 3.11 |
| Kubernetes | ≥ 1.21 (CronJob `batch/v1`, PDB `policy/v1`); Ingress `networking.k8s.io/v1` (≥ 1.19); HPA `autoscaling/v2` (≥ 1.23). Le risorse non servite dal cluster sono segnalate come "non supportate", senza errori bloccanti |
| Podman | 4.x / 5.x (API libpod `/v4.0.0/libpod`) — opzionale |
| metrics-server / Prometheus | opzionali |

## Modalità LIVE e DEMO

- **LIVE** (`mode: live`): dati reali; badge verde `LIVE · <contesto>`.
- **DEMO** (`mode: demo`): cluster e Podman simulati in memoria, banner viola a righe "MODALITÀ DEMO" su ogni pagina,
  header HTTP `X-PKM-Mode: demo`. Consentita solo con `environment: development`: con `production` il servizio non parte.

## Documentazione

[INSTALL.md](INSTALL.md) · [OPERATIONS.md](OPERATIONS.md) · [SECURITY.md](SECURITY.md) · [TROUBLESHOOTING.md](TROUBLESHOOTING.md) ·
[BACKUP.md](BACKUP.md) · [DEVELOPMENT.md](DEVELOPMENT.md) · [ARCHITECTURE.md](ARCHITECTURE.md) · [CHANGELOG.md](CHANGELOG.md) ·
[API](docs/api/README.md) · [Decisioni architetturali](docs/architecture-decisions/)

## Licenza

Proprietary (vedi `backend/pyproject.toml`).
