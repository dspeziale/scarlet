# Analisi architetturale — Scarlet e piattaforma Docker interna

Data analisi: 2026-09-30
Repository: `github.com/dspeziale/scarlet` (branch `main`)

---

## 1. Situazione attuale

### 1.1 Stato del repository

L'analisi è stata eseguita sul repository così come si presentava all'avvio del lavoro.

| Voce | Rilevato |
|------|----------|
| File presenti nella working tree | solo `prompt.txt` (specifica del lavoro) |
| File presenti in `HEAD` | nessuno (commit `29ac2f4` ha rimosso tutti i file) |
| Storia git | 8 commit; fino a `1d765b8` esisteva un progetto Python/Flask di ~290 file |
| Branch | solo `main` |
| Remote | `https://github.com/dspeziale/scarlet.git` |
| Dockerfile esistente | nessuno (nella working tree) |
| Compose esistente | nessuno |
| GitHub Actions esistenti | nessuna |
| README / documentazione | nessuna |
| File di ambiente / configurazione | nessuno |
| Secrets hardcoded | nessuno (non c'è codice) |
| Dipendenze esterne | nessuna dichiarata |
| Porte, database, volumi, logging, health check | non definiti |

Il proprietario del repository ha confermato esplicitamente che **si riparte da zero**.

### 1.2 Cosa era Scarlet in precedenza (solo contesto)

La storia git mostra che Scarlet era un "control plane" molto ampio (Flask, Celery, Redis,
PostgreSQL, adapter Docker/Podman/Kubernetes, Helm chart, console web AdminLTE). Quel progetto è
stato rimosso volutamente: era in contrasto con il principio fondamentale della nuova specifica
("non un sistema inutilmente complesso", "no Kubernetes salvo necessità documentata").

Questa analisi **non riutilizza** quel codice. Ne tiene conto solo per due informazioni utili:

* il team lavora in Python (3.12) e conosce PostgreSQL;
* i server target sono Linux (in passato Oracle Linux; vedi ASSUMPTION A2).

### 1.3 Ambiente di lavoro rilevato

| Voce | Rilevato |
|------|----------|
| Workstation | Windows 11, Git Bash, Python 3.12.10, Docker 29.8 (Linux containers), Compose v5.5 |
| Accesso a PyPI | disponibile |
| `gh` CLI | non installato in locale (non necessario: i workflow usano `gh` dei runner GitHub) |
| Server di sviluppo / produzione | **non raggiungibili / non noti** (vedi sezione 8) |

---

## 2. Problemi individuati

| # | Problema | Conseguenza |
|---|----------|-------------|
| P1 | Il repository è vuoto: non esiste un'applicazione da containerizzare | Occorre definire Scarlet come applicazione minimale ma reale, che rispetti il "contratto" della piattaforma (health, versione, log, config via ambiente) |
| P2 | Non esiste alcuna pipeline, registry, standard di deploy | Tutto va costruito, ma può essere costruito "pulito" senza vincoli legacy |
| P3 | Nessuna informazione sui server (SO, rete, DNS, certificati) | Le parti dipendenti dall'infrastruttura sono progettate in modo parametrico e marcate come REQUIRED/ASSUMPTION |
| P4 | Il team è all'inizio dell'adozione di Docker | La soluzione deve nascondere Docker dietro un'interfaccia applicativa (`appctl`) e una documentazione che non presuppone competenze avanzate |
| P5 | Storia git con messaggi non significativi ("dsd", "kfkfkf") | Da qui in avanti: commit piccoli, con messaggi descrittivi; branch protection su `main` |

---

## 3. Assunzioni (ASSUMPTION)

Ogni assunzione è numerata e richiamata nel resto della documentazione. Se un'assunzione è
errata, la sezione "Impatto" dice cosa cambia.

| ID | Assunzione | Impatto se errata |
|----|------------|-------------------|
| A1 | **Scarlet** viene ridefinita come un piccolo servizio web Python (FastAPI) con PostgreSQL: un "inventario dei rilasci" che registra quale versione di quale applicazione è deployata in quale ambiente. È volutamente piccolo: serve da prima applicazione reale e da modello per le successive | Se l'applicazione reale è un'altra, si sostituisce il contenuto di `src/` mantenendo il contratto (health endpoint, `/version`, config via env, Dockerfile, `deploy/`). La piattaforma non cambia |
| A2 | I server sono Linux con systemd: **Ubuntu Server 24.04 LTS** è la distribuzione di riferimento per le procedure; Oracle Linux / RHEL 9 sono supportati con le varianti indicate in `INSTALLATION.md` | Solo i comandi di installazione pacchetti cambiano |
| A3 | Esistono (o esisteranno) **due server distinti**: uno DEVELOPMENT e uno PRODUCTION, entrambi con accesso in uscita verso `ghcr.io` (HTTPS) | Se unico server: i due ambienti convivono in due directory distinte (`/opt/apps/scarlet-dev`, `/opt/apps/scarlet`), supportato ma sconsigliato per la produzione |
| A4 | Il registry è **GitHub Container Registry (GHCR)** con package **privato** | Se pubblico: non serve l'utente tecnico per il pull (vedi A5) |
| A5 | Per il pull di immagini private dal server si usa un **utente GitHub tecnico** (machine user) con PAT `read:packages` conservato sul server in un file `0600`. GitHub non offre OIDC per il pull da un server esterno | Se GitHub App o package pubblico: cambia solo `platform/server/registry-login.sh` |
| A6 | I server **non sono raggiungibili da Internet in ingresso**; i runner GitHub-hosted devono poter aprire una connessione SSH verso i server (regola firewall sugli IP dei runner) **oppure** si installa un **self-hosted runner** in rete interna. La pipeline supporta entrambi tramite la variabile `DEPLOY_RUNNER` | Nessun impatto sul codice; solo configurazione |
| A7 | Il database PostgreSQL è **containerizzato sullo stesso server** dell'applicazione, con dati su bind mount e backup giornaliero `pg_dump`. È la scelta più semplice per la prima applicazione; il passaggio a un DB esterno richiede solo di togliere un file compose e cambiare `DATABASE_URL` | Se DB esterno gestito: si usa la variante documentata in `DEPLOYMENT.md`; il backup del DB passa al DBA |
| A8 | L'applicazione è raggiunta via HTTPS da rete interna tramite **Caddy** come reverse proxy condiviso per tutte le app del server; il certificato è fornito dalla CA interna aziendale (oppure ACME se il DNS è pubblico). Non conoscendo i nomi DNS, il file `Caddyfile` usa segnaposto | Va indicato il nome DNS e la modalità certificati (sezione 8) |
| A9 | Strategia di deploy iniziale **recreate con verifica health e rollback automatico**: alcuni secondi di indisponibilità a ogni deploy sono accettabili per la prima applicazione | Se non accettabili: evoluzione blue/green con Caddy, documentata in `DEPLOYMENT.md` |
| A10 | Valori iniziali di DR: **RPO 24 ore** (backup notturno), **RTO 4 ore** (reinstallazione da guida + restore) | Da confermare con il business; se servono valori più stringenti va prevista replica DB e backup off-site più frequente |
| A11 | Le migrazioni DB seguono la regola **"backward compatible"** (expand/contract): la versione N+1 dello schema deve funzionare con il codice della versione N, così il rollback applicativo non richiede rollback dello schema | Se violata: il rollback richiede restore da backup (procedura in `ROLLBACK.md`) |
| A12 | Non serve una Web UI nella prima versione: `appctl` + storico deployment su GitHub coprono i requisiti; la UI è documentata come evoluzione | Se richiesta subito: `ARCHITECTURE.md` §9 descrive come aggiungerla senza esporre il socket Docker |

---

## 4. Rischi

| Rischio | Probabilità | Impatto | Mitigazione |
|---------|-------------|---------|-------------|
| I runner GitHub non raggiungono i server (firewall) | Alta | Alto (nessun deploy automatico) | Self-hosted runner in rete interna, già supportato dai workflow; fallback: `appctl deploy <tag>` manuale da un operatore |
| L'utente `deploy` appartiene al gruppo `docker` (equivale a root sull'host) | Certa | Medio | Chiave SSH della pipeline con `command=` forzato (solo sottocomandi `appctl` ammessi); operatori senza accesso al socket, usano `sudo -u deploy appctl` con sudoers ristretto; socket mai esposto in rete; evoluzione futura: rootless Docker |
| Deploy con health fallita in produzione | Media | Alto | Health gate + rollback automatico alla versione precedente; immagine precedente sempre presente localmente e nel registry |
| Migrazione DB non retro-compatibile rende impossibile il rollback | Media | Alto | Regola A11 documentata; backup automatico pre-migrazione a ogni deploy in produzione; restore documentato |
| Disco pieno per log o immagini vecchie | Media | Alto | Log driver con `max-size`/`max-file`; `appctl deploy` conserva solo le ultime N release e fa `image prune` mirato; `appctl doctor` segnala disco > 80% |
| Perdita del server (nessun backup off-site definito) | Bassa | Alto | Backup locale giornaliero + TODO esplicito per copia remota (`BACKUP.md`); tutto il resto è ricreabile da git + registry |
| Immagine con vulnerabilità critiche pubblicata | Media | Medio | Trivy blocca la pipeline su HIGH/CRITICAL con fix disponibile; Dependabot su pip, Actions e immagini base |
| Deploy concorrenti sullo stesso ambiente | Bassa | Medio | `concurrency` per ambiente in GitHub Actions + lock file esclusivo in `appctl` |
| PAT del machine user compromesso | Bassa | Medio | Scope minimo `read:packages`, file `0600` su server, rotazione documentata in `SECRETS.md` |
| Team senza esperienza Docker fa operazioni dirette con `docker` | Media | Medio | Modello operativo "solo `appctl`", runbook, `doctor` per la diagnosi; operatori senza gruppo docker |

---

## 5. Proposta architetturale

Sintesi (dettagli e diagrammi in `ARCHITECTURE.md`):

```
sviluppatore ──push──▶ GitHub (main) ──▶ CI: lint, test, pip-audit, gitleaks
                                              │
                                              ▼
                                     build immagine (una sola volta)
                                     tag immutabile git-<sha12>
                                     scan Trivy ──▶ push GHCR
                                              │
                                              ▼
                              deploy DEVELOPMENT (SSH ▶ appctl deploy git-<sha12>)
                              health + smoke test
                                              │
                            workflow "promote-production" (manuale)
                            verifica: immagine esiste, deploy DEV riuscito
                            approvazione (GitHub Environment production)
                                              │
                                              ▼
                              deploy PRODUCTION (stessa immagine, stesso tag)
                              health + smoke test, rollback automatico se fallisce
```

Componenti:

* **Applicazione**: FastAPI + PostgreSQL, immagine `python:3.12-slim` multi-stage, utente non-root,
  filesystem read-only, health `/health` e `/ready`, `/version` con commit e tag.
* **Bundle di deploy dentro l'immagine** (`/deploy`): i file compose viaggiano con l'immagine, così
  "stessa immagine" significa anche "stessa configurazione di deploy" e non serve copiare file via SCP.
* **Registry**: GHCR, autenticazione via `GITHUB_TOKEN` in CI (nessuna credenziale statica nel repo).
* **Server**: Docker Engine + Compose v2, layout `/opt/apps/<app>/`, utente `deploy`, proxy Caddy
  condiviso, restart policy `unless-stopped`, backup via systemd timer.
* **appctl** (Python 3, solo libreria standard): `status`, `start`, `stop`, `restart`, `deploy`,
  `rollback`, `logs`, `health`, `version`, `history`, `doctor`, `backup`. Audit log append-only.
* **GitHub Actions**: `ci.yml` (build once + deploy dev), `deploy.yml` (riutilizzabile),
  `promote-production.yml` (manuale con approvazione), `rollback.yml`, `release-tag.yml`
  (tag semver senza rebuild), `registry-cleanup.yml`.

---

## 6. Alternative considerate e motivazioni

| Area | Scelta | Alternative | Motivazione |
|------|--------|-------------|-------------|
| Orchestrazione | Docker Compose su singolo host per ambiente | Kubernetes, Swarm, Nomad | Nessun requisito di scalabilità orizzontale o multi-nodo; il team è all'inizio; Compose è leggibile e sufficiente. K8s solo se emergerà HA reale |
| Registry | GHCR | Docker Hub, Harbor, registry self-hosted | Integrato con GitHub (permessi, `GITHUB_TOKEN`, Dependabot); zero infrastruttura da gestire; Harbor solo se serviranno policy on-prem |
| Tagging | `git-<sha12>` immutabile + `vX.Y.Z` opzionale (alias, senza rebuild) | solo `latest`, build number | Tracciabilità diretta al commit; il tag semver è un alias dello stesso digest |
| Meccanismo di deploy | GitHub Actions → SSH → `appctl deploy` | Agente pull (Watchtower), GitOps, runner sul server che fa `compose up` | SSH con forced command è semplice, auditabile, senza componenti sempre attivi sul server; Watchtower toglie controllo su cosa e quando; GitOps richiede un agente aggiuntivo |
| Trasporto dei file compose | dentro l'immagine (`/deploy`) | SCP dalla pipeline, checkout git sul server, artifact GitHub | Un solo artefatto immutabile; niente git né token repo sul server; gli artifact GitHub scadono |
| Strategia di deploy | Recreate + health gate + auto-rollback | Rolling, blue/green, canary | Con singolo host e Compose il rolling non è nativo; blue/green raddoppia la memoria e complica DB/migrazioni; downtime di pochi secondi accettabile (A9) |
| CLI | Python 3 (stdlib) | Bash, Go | Bash diventa fragile oltre le 300 righe (parsing JSON, lock, errori); Go richiede toolchain e distribuzione binari; Python 3 è già presente su tutte le distro server, la stdlib basta (`subprocess`, `json`, `fcntl`, `urllib`) ed è testabile con pytest |
| Reverse proxy | Caddy | Nginx, Traefik | Caddy gestisce TLS (ACME o certificati forniti) con configurazione di 10 righe; Nginx richiede certbot e più configurazione; Traefik è più potente ma con curva di apprendimento maggiore |
| Avvio dopo reboot | restart policy `unless-stopped` + `docker.service` abilitato | Unit systemd per app | Una sola fonte di verità sullo stato (Docker); una unit systemd in più genera conflitti (chi comanda?). systemd usato solo per il timer di backup |
| Database | PostgreSQL containerizzato con bind mount (A7) | DB esterno, DB in named volume | Bind mount rende backup e restore comprensibili; passaggio a DB esterno documentato |
| Secrets | GitHub Environments (pipeline) + file `0600` sul server | Vault, Docker secrets (Swarm), SOPS | Il livello richiesto è coperto; Vault è un'infrastruttura in più; Docker secrets in Compose non-Swarm sono file mount, equivalenti al file protetto |
| Scanning | ruff, pip-audit, gitleaks, Trivy, Dependabot | CodeQL, Snyk | Coprono lint, dipendenze, secrets, immagine, aggiornamenti. CodeQL richiede licenza GitHub Advanced Security su repo privati: RECOMMENDED, workflow non incluso |
| Web UI | rimandata | Portainer, UI custom | Portainer è una "Docker management UI" generica (vietata dalla specifica); una UI custom sicura è un progetto a sé; `appctl` + GitHub coprono le operazioni |

---

## 7. Decisioni sulla struttura dei privilegi

```
operatore (account personale, gruppo appops)
   │  sudo -u deploy appctl <comando>      (sudoers: solo /usr/local/bin/appctl)
   ▼
utente deploy (gruppo docker, owner di /opt/apps/*)
   │  appctl: solo operazioni applicative, con audit
   ▼
Docker Engine (socket unix locale, mai in rete)
```

* La pipeline entra via SSH come `deploy` con chiave dedicata e `command="appctl-ssh-gate"`:
  può eseguire solo `appctl deploy|rollback|status|health|version`.
* L'audit log (`/var/log/apps/<app>/audit.log`) è di proprietà di root con attributo append-only
  (`chattr +a`): `appctl` può solo aggiungere righe.

---

## 8. Informazioni che devono essere fornite dall'amministratore

### BLOCKER (bloccano il go-live, non l'implementazione)

| ID | Informazione | Perché serve |
|----|--------------|--------------|
| B1 | Indirizzi/hostname dei server DEVELOPMENT e PRODUCTION, utente SSH iniziale con sudo | Installazione server, secrets `DEPLOY_HOST` negli Environments GitHub |
| B2 | Modalità con cui i runner raggiungono i server (apertura firewall verso runner GitHub-hosted **oppure** self-hosted runner) | Senza questo la pipeline non può fare deploy; il resto funziona (build, scan, push) |

### REQUIRED (necessarie per la configurazione, valori di default forniti)

| ID | Informazione | Default adottato |
|----|--------------|------------------|
| R1 | Nome DNS dell'applicazione per ambiente (es. `scarlet-dev.intranet.local`, `scarlet.intranet.local`) | segnaposto `scarlet.example.internal` nel `Caddyfile` |
| R2 | Modalità certificati TLS: CA interna (fornire cert+key), ACME pubblico, o CA interna di Caddy | `tls internal` (certificato di Caddy) per DEV; produzione da definire |
| R3 | Utente GitHub tecnico (machine user) con PAT `read:packages` per i server | ASSUMPTION A5 |
| R4 | Chi approva le promozioni in produzione (nomi GitHub per "required reviewers") | nessuno impostato: va configurato nell'Environment `production` |
| R5 | Visibilità del package GHCR (privato/pubblico) | privato |
| R6 | Dimensionamento server (default proposto: 2 vCPU, 4 GB RAM, 40 GB disco) | vedi `INSTALLATION.md` |

### RECOMMENDED

| ID | Informazione |
|----|--------------|
| C1 | Destinazione off-site per i backup (NFS/S3-compatibile/altro) |
| C2 | Licenza GitHub Advanced Security (CodeQL, secret scanning con push protection su repo privati) |
| C3 | Policy aziendale di retention dei log e degli audit (default proposto: 90 giorni) |
| C4 | Canale di notifica (email/Teams) per esito deploy: i workflow espongono un riepilogo, il webhook è un TODO |
| C5 | Distribuzione Linux effettiva dei server (A2) |

### ASSUMPTION

Vedi sezione 3 (A1–A12).

---

## 9. Piano di implementazione

| Fase | Contenuto | Verifica |
|------|-----------|----------|
| 1 | Questo documento | revisione |
| 2 | `docs/ARCHITECTURE.md` con diagrammi Mermaid | revisione |
| 3 | Applicazione Scarlet, Dockerfile, `.dockerignore`, compose, `.env.example` | `ruff`, `pytest`, `docker build`, `docker compose config`, avvio locale con health OK |
| 4 | `ci.yml` (lint, test, security, build, scan) | validazione YAML + actionlint |
| 5 | Registry: naming, login, cleanup, Dependabot | `release-tag.yml`, `registry-cleanup.yml` |
| 6 | Deploy development (`deploy.yml`, SSH gate, `platform/ci/remote-deploy.sh`) | test failure SSH |
| 7 | Promozione produzione (`promote-production.yml`, environments, `rollback.yml`) | validazione |
| 8 | `appctl` | unit test pytest |
| 9 | logging, health, audit, `doctor`, `history` | unit test |
| 10 | Sicurezza: hardening compose, sudoers, SSH gate, proxy Caddy, install script | `docker compose config`, shellcheck |
| 11 | Rollback (automatico e manuale) | test integrazione |
| 12 | Test di integrazione con Docker reale (deploy ok, idempotenza, unhealthy → rollback, immagine inesistente, porta occupata, registry non disponibile, SSH non disponibile) | esecuzione in ambiente Linux + CI |
| 13 | Documentazione completa | revisione incrociata con il codice |
| 14 | Audit finale | checklist in `docs/AUDIT_FINALE.md` |

---

## 10. Struttura repository proposta

```
scarlet/
├── README.md
├── Dockerfile
├── .dockerignore
├── .gitignore  .gitattributes  .editorconfig
├── pyproject.toml            # app + tooling (ruff, pytest)
├── requirements.txt          # dipendenze runtime bloccate
├── requirements-dev.txt
├── Makefile                  # comandi sviluppatore (lint, test, build, run)
├── alembic.ini
├── migrations/               # migrazioni DB (Alembic)
├── src/scarlet/              # applicazione FastAPI
├── tests/app/                # unit test applicazione
├── deploy/                   # bundle copiato nell'immagine in /deploy
│   ├── compose.yaml          # servizio app (comune)
│   ├── compose.db.yaml       # PostgreSQL containerizzato (opzionale)
│   ├── compose.dev.yaml      # override development
│   ├── compose.prod.yaml     # override production
│   ├── env/development.env   # configurazione non sensibile
│   ├── env/production.env
│   └── secrets.env.example
├── platform/                 # piattaforma riutilizzabile per tutte le app
│   ├── appctl/               # CLI operativa (Python stdlib) + test
│   ├── server/               # install script, sudoers, systemd, template app.conf, SSH gate
│   ├── proxy/                # Caddy condiviso
│   ├── ci/                   # script usati dai workflow (deploy remoto via SSH)
│   └── tests/integration/    # test end-to-end con Docker reale
├── .github/
│   ├── workflows/            # ci, deploy (reusable), promote-production, rollback, release-tag, registry-cleanup
│   ├── dependabot.yml
│   └── CODEOWNERS
└── docs/                     # documentazione (elenco in README)
```

Quando le applicazioni saranno più di una, `platform/` sarà spostato in un repository dedicato
(`docker-platform`) e ogni applicazione conterrà solo `Dockerfile`, `deploy/` e i workflow che
richiamano quelli riutilizzabili. Il layout è già pensato per questo passaggio.
