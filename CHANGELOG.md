# Changelog

Formato: [Keep a Changelog](https://keepachangelog.com/it/1.1.0/), versioni [SemVer](https://semver.org/lang/it/).

## [1.0.0] - 2026-10-19

### Added
- Console web (React/TypeScript) con menu laterale a sottomenu espandibili e persistenti, modalità compatta, layout responsive, temi chiaro/scuro, italiano e inglese.
- Backend FastAPI con API REST versionate `/api/v1`, OpenAPI, Server-Sent Events per notifiche e log live.
- Integrazione Kubernetes: 20 tipi di risorsa (Nodes, Namespaces, Events, Pods, Deployments, ReplicaSets, StatefulSets, DaemonSets, Jobs, CronJobs, Services, Ingress, Endpoints, PV, PVC, StorageClasses, ConfigMaps, Secrets, PodDisruptionBudgets, HPA), dettaglio con vista semplice, relazioni, eventi, log, metriche, YAML/JSON, diagnostica.
- Dashboard operativa e Centro Operativo con rilevamento automatico dei problemi, controlli calcolati dai dati, causa più probabile, rischio e azioni.
- Orchestrazione: scale, rolling restart, pause/resume, cronologia revisioni con confronto e rollback, CronJob suspend/trigger, cordon/uncordon/drain con Eviction API e avanzamento.
- Editor YAML con lint, validazione server-side dry-run, diff e server-side apply.
- Wizard *Onboarding immagine* (verifica sul registry e analisi dell'immagine) e *Wizard di deploy* in 12 passi con riepilogo, rischi, YAML e dry-run.
- Integrazione Podman separata: runtime, container, immagini, registry, log, statistiche.
- Monitoraggio: CPU, memoria, storage, health, alta affidabilità, eventi, visualizzatore log; metrics-server e Prometheus opzionale con query in whitelist.
- Notifiche con stati aperta/gestita/risolta; ricerca globale (Ctrl+K).
- Guida online integrata IT/EN (57 articoli) ricercabile e contestuale.
- Sicurezza: utenti locali Argon2id, RBAC Administrator/Operator/Viewer nel backend, sessioni lato server, CSRF, rate limiting, CSP, audit log con ricerca ed export CSV.
- Backup dell'applicazione (DB, configurazione, export opzionale dei manifest) con checksum, verifica, retention, timer giornaliero e restore.
- Wizard di prima installazione con token monouso.
- Script `install.sh`, `upgrade.sh` (rollback automatico), `uninstall.sh`, `backup.sh`, `restore.sh`, `make-kubeconfig.sh`, `build-release.sh`; unit systemd con hardening; ClusterRole `pkm-operator`/`pkm-readonly`; immagine container e unit Quadlet per Podman.
- Modalità DEMO con dati simulati, rifiutata in produzione.
- Test: backend (unit, API, sicurezza, failure, integrazione con kind e Podman reali), frontend (vitest), end-to-end (Playwright), installazione su Oracle Linux 9 con systemd.
