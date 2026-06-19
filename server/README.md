# SOC Seattle — Server

Backend centralizzato multi-tenant per la gestione di probe Linux distribuite.

## Indice

- [Architettura](#architettura)
- [Stack Tecnologico](#stack-tecnologico)
- [Setup Rapido](#setup-rapido)
- [Configurazione](#configurazione)
- [API Reference](#api-reference)
- [Flusso Registrazione Probe](#flusso-registrazione-probe)
- [Sistema Crittografico](#sistema-crittografico)
- [RBAC](#rbac)
- [Test](#test)
- [Deploy](#deploy)

---

## Architettura

### Visione d'insieme

```mermaid
graph TB
    subgraph "Client Layer"
        Browser["Browser\n(AdminLTE 4)"]
        ProbeAgent["Probe Agent\n(Docker Container)"]
    end

    subgraph "Server — Flask / Vercel"
        WebBP["Web Blueprint\n/dashboard /superadmin"]
        APIBP["API v1 Blueprint\n/api/v1/"]

        subgraph "Auth & Security"
            JWT["JWT Extended"]
            RBAC["RBAC Decorators"]
            Limiter["Rate Limiter"]
        end

        subgraph "Middleware"
            CorrID["Correlation ID"]
            TenantCtx["Tenant Context"]
            AuditMW["Audit Middleware"]
        end

        subgraph "API Routes"
            AuthAPI["/auth"]
            TenantAPI["/tenants"]
            UserAPI["/users"]
            ProbeAPI["/probes /probe/*"]
            TaskAPI["/tasks"]
            TelAPI["/telemetry"]
            AccAPI["/accounting"]
            AuditAPI["/audit"]
        end

        subgraph "Services"
            AuthSvc["AuthService"]
            TenantSvc["TenantService"]
            UserSvc["UserService"]
            ProbeSvc["ProbeService"]
            TaskSvc["TaskService"]
            TelSvc["TelemetryService"]
            AccSvc["AccountingService"]
        end

        subgraph "Crypto"
            X25519["X25519 DH"]
            Ed25519["Ed25519 Sign"]
            AESGCM["AES-256-GCM"]
            HKDF["HKDF-SHA256"]
        end

        subgraph "Repositories"
            TenantRepo["TenantRepo"]
            UserRepo["UserRepo"]
            ProbeRepo["ProbeRepo"]
            TaskRepo["TaskRepo"]
            AuditRepo["AuditRepo"]
        end
    end

    subgraph "Database — PostgreSQL / NeonDB"
        Tenants["tenants"]
        Users["users"]
        Roles["roles / permissions"]
        Probes["probes"]
        ProbeTokens["probe_registration_tokens"]
        ProbeKeys["probe_keys"]
        Tasks["tasks / assignments / results"]
        Telemetry["device/service/wifi/ble inventory"]
        Accounting["usage_accounting"]
        AuditLog["audit_logs (immutable)"]
        TokenBL["token_blocklist"]
    end

    Browser --> WebBP
    Browser --> APIBP
    ProbeAgent --> APIBP

    APIBP --> JWT --> RBAC
    APIBP --> CorrID --> TenantCtx --> AuditMW

    WebBP --> AuthAPI
    APIBP --> AuthAPI & TenantAPI & UserAPI & ProbeAPI & TaskAPI & TelAPI & AccAPI & AuditAPI

    AuthAPI --> AuthSvc
    TenantAPI --> TenantSvc
    UserAPI --> UserSvc
    ProbeAPI --> ProbeSvc --> X25519 & Ed25519 & AESGCM & HKDF
    TaskAPI --> TaskSvc
    TelAPI --> TelSvc
    AccAPI --> AccSvc

    AuthSvc --> UserRepo
    TenantSvc --> TenantRepo
    UserSvc --> UserRepo
    ProbeSvc --> ProbeRepo
    TaskSvc --> TaskRepo
    TelSvc --> TenantRepo
    AccSvc --> TenantRepo

    TenantRepo --> Tenants
    UserRepo --> Users & Roles
    ProbeRepo --> Probes & ProbeTokens & ProbeKeys
    TaskRepo --> Tasks
    AuditRepo --> AuditLog
```

### Modello Multi-Tenant

```mermaid
erDiagram
    TENANTS {
        uuid id PK
        string name UK
        string slug UK
        string plan
        int max_probes
        bool is_active
    }
    USERS {
        uuid id PK
        uuid tenant_id FK
        string email UK
        string username UK
        string password_hash
        bool is_superadmin
        bool mfa_enabled
    }
    ROLES {
        uuid id PK
        string name UK
        bool is_system
    }
    PERMISSIONS {
        uuid id PK
        string resource
        string action
    }
    PROBES {
        uuid id PK
        uuid tenant_id FK
        uuid uuid UK
        string hostname
        string machine_id
        string status
        string public_sign_key
        string public_exchange_key
        string server_side_fingerprint
        bool key_provisioned
    }
    PROBE_REGISTRATION_TOKENS {
        uuid id PK
        uuid tenant_id FK
        string token UK
        datetime expires_at
        bool used
    }
    TASKS {
        uuid id PK
        uuid tenant_id FK
        string task_type
        string status
        json parameters
    }
    TASK_ASSIGNMENTS {
        uuid id PK
        uuid task_id FK
        uuid probe_id FK
        uuid tenant_id FK
        string status
    }
    TASK_RESULTS {
        uuid id PK
        uuid assignment_id FK
        json result_data
        string status
    }
    AUDIT_LOGS {
        uuid id PK
        uuid tenant_id FK
        uuid user_id FK
        string action
        string resource_type
        datetime timestamp
    }
    USAGE_ACCOUNTING {
        uuid id PK
        uuid tenant_id FK
        uuid probe_id FK
        date period_date
        float cpu_seconds
        float memory_mb
        int task_count
    }

    TENANTS ||--o{ USERS : "has"
    TENANTS ||--o{ PROBES : "owns"
    TENANTS ||--o{ TASKS : "creates"
    USERS }o--o{ ROLES : "assigned"
    ROLES }o--o{ PERMISSIONS : "grants"
    PROBES ||--o{ TASK_ASSIGNMENTS : "receives"
    TASKS ||--o{ TASK_ASSIGNMENTS : "assigned_via"
    TASK_ASSIGNMENTS ||--o| TASK_RESULTS : "produces"
    TENANTS ||--o{ AUDIT_LOGS : "recorded_in"
    TENANTS ||--o{ USAGE_ACCOUNTING : "tracked_in"
```

### Flusso Registrazione Probe

```mermaid
sequenceDiagram
    participant TA as TenantAdmin
    participant S as Server
    participant P as Probe (Docker)
    participant DB as Database

    TA->>S: POST /api/v1/probe-tokens {label, expiry_hours}
    S->>DB: INSERT probe_registration_tokens (PRB-XXXXXXXXXXXX)
    S-->>TA: {token: "PRB-XXXXXXXXXXXX"}

    Note over P,S: Phase 1 — Registration
    P->>S: POST /api/v1/probe/register {registration_token, hostname, machine_id, ...}
    S->>DB: Validate token (not used, not expired)
    S->>DB: INSERT probes (status=pending_keys)
    S->>DB: UPDATE token (used=true)
    S-->>P: {probe_id, probe_uuid, status: "pending_keys"}

    Note over P,S: Phase 2 — Key Provisioning (X25519 DH)
    P->>P: Generate X25519 keypair (probe_priv, probe_pub)
    P->>P: Generate Ed25519 keypair (probe_sign_priv, probe_sign_pub)
    P->>S: POST /api/v1/probe/provision-keys {probe_id, probe_sign_public_key, probe_exchange_public_key}
    S->>S: Generate server X25519 keypair (ephemeral)
    S->>S: Generate server Ed25519 keypair (ephemeral)
    S->>S: X25519 DH → shared_secret
    S->>S: HKDF-SHA256 → {session_key, transport_key, rotation_key}
    S->>S: Compute fingerprint = SHA256(probe_pub || server_pub)
    S->>S: Sign fingerprint with server Ed25519 priv
    S->>DB: UPDATE probes (public_sign_key, public_exchange_key, server_sign_public_key, fingerprint)
    Note over S: Server DISCARDS private keys and derived session keys
    S-->>P: {server_sign_public_key, server_exchange_public_key, salt, fingerprint, signature}

    P->>P: Verify server signature
    P->>P: X25519 DH → shared_secret (same)
    P->>P: HKDF-SHA256 → {session_key, transport_key, rotation_key}
    Note over P: Probe stores derived keys locally for transport encryption

    Note over P,S: Phase 3 — Normal Operation
    P->>S: POST /api/v1/probe/heartbeat {probe_id, metrics}
    S->>DB: UPDATE probes (status=online, last_seen)
    P->>S: GET  /api/v1/probe/{id}/tasks
    P->>S: POST /api/v1/probe/{id}/tasks/{id}/result {result_data}
    P->>S: POST /api/v1/telemetry/devices {devices[]}
```

### RBAC

```mermaid
graph LR
    SA["SuperAdmin\n(is_superadmin=true)"] -->|full access| Everything

    TA["TenantAdmin"] --> own_users["manage own users"]
    TA --> probe_tokens["generate probe tokens"]
    TA --> own_probes["view/manage own probes"]
    TA --> schedule_tasks["schedule tasks"]
    TA --> own_audit["view own audit"]
    TA --> accounting["view accounting"]

    OP["Operator"] --> read_probes["read probes"]
    OP --> create_tasks["create/run authorised tasks"]
    OP --> read_results["read results + telemetry"]

    RO["ReadOnly"] --> read_only["read probes, tasks, telemetry, audit"]
```

---

## Stack Tecnologico

| Layer | Tecnologia |
|-------|-----------|
| Runtime | Python 3.12 |
| Web framework | Flask 3.0 |
| ORM | SQLAlchemy 2.0 + Flask-Migrate |
| Database | PostgreSQL (NeonDB in produzione) |
| Auth | Flask-JWT-Extended + Argon2id |
| Crittografia | PyNaCl / cryptography (X25519, Ed25519, AES-GCM, HKDF) |
| Rate limiting | Flask-Limiter |
| Security headers | Flask-Talisman |
| CORS | Flask-CORS |
| Logging | structlog (JSON) |
| API docs | flasgger (OpenAPI 3) |
| Frontend | AdminLTE 4 + Bootstrap 5 |
| Deploy | Vercel / Gunicorn |
| Test | Pytest + pytest-cov |

---

## Setup Rapido

### Con Docker Compose (raccomandato)

```bash
cd server
cp .env.example .env
# Editare .env con le proprie credenziali
docker compose up --build
```

Il server sarà disponibile su `http://localhost:5000`.

### Manuale

```bash
cd server
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# Editare DATABASE_URL, SECRET_KEY, JWT_SECRET_KEY

# Creare il database
flask --app app db init
flask --app app db migrate -m "initial"
flask --app app db upgrade

# Seed (crea ruoli e SuperAdmin)
python seed.py

# Avviare
flask --app app run --debug
```

---

## Configurazione

Tutte le variabili d'ambiente sono documentate in `.env.example`.

| Variabile | Default | Descrizione |
|-----------|---------|-------------|
| `SECRET_KEY` | — | Chiave segreta Flask (obbligatorio in produzione) |
| `JWT_SECRET_KEY` | `SECRET_KEY` | Chiave firma JWT |
| `DATABASE_URL` | — | Stringa connessione PostgreSQL |
| `FLASK_ENV` | `development` | `development` / `testing` / `production` |
| `PROBE_TOKEN_EXPIRY_HOURS` | `24` | Durata validità token registrazione probe |
| `KEY_ROTATION_DAYS` | `30` | Frequenza rotazione chiavi raccomandata |
| `LOG_LEVEL` | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |
| `LOG_FORMAT` | `json` | `json` / `console` |
| `CORS_ORIGINS` | `*` | Origini CORS consentite (virgola-separato) |
| `FORCE_HTTPS` | `false` | Forza redirect HTTPS |
| `SUPERADMIN_EMAIL` | `admin@soc-seattle.local` | Email SuperAdmin creato da seed |
| `SUPERADMIN_PASSWORD` | `ChangeMe!2025` | **Cambiare in produzione!** |

---

## API Reference

Tutte le API sono sotto `/api/v1/`. Autenticazione via `Authorization: Bearer <token>`.

### Autenticazione

| Metodo | Endpoint | Accesso | Descrizione |
|--------|----------|---------|-------------|
| POST | `/auth/login` | Pubblico | Login, ritorna access + refresh token |
| POST | `/auth/refresh` | Refresh token | Nuovi access token |
| DELETE | `/auth/logout` | JWT | Revoca access token |
| GET | `/auth/me` | JWT | Profilo utente corrente |
| POST | `/auth/mfa/setup` | JWT | Genera secret TOTP |
| POST | `/auth/mfa/verify` | JWT | Attiva MFA |

### Tenant (solo SuperAdmin)

| Metodo | Endpoint | Descrizione |
|--------|----------|-------------|
| GET | `/tenants` | Lista tutti i tenant |
| POST | `/tenants` | Crea nuovo tenant |
| GET | `/tenants/<id>` | Dettaglio tenant |
| PATCH | `/tenants/<id>` | Aggiorna tenant |
| DELETE | `/tenants/<id>` | Disattiva tenant |

### Utenti

| Metodo | Endpoint | Accesso | Descrizione |
|--------|----------|---------|-------------|
| GET | `/users` | SA / TenantAdmin | Lista utenti (scoped per tenant) |
| POST | `/users` | SA / TenantAdmin | Crea utente |
| GET | `/users/<id>` | SA / TenantAdmin | Dettaglio utente |
| PATCH | `/users/<id>` | SA / TenantAdmin | Aggiorna utente |
| POST | `/users/<id>/roles` | SA / TenantAdmin | Assegna ruolo |

### Probe

| Metodo | Endpoint | Accesso | Descrizione |
|--------|----------|---------|-------------|
| POST | `/probe/register` | **Pubblico** | Fase 1: Registrazione probe |
| POST | `/probe/provision-keys` | **Pubblico** | Fase 2: Scambio chiavi X25519 |
| POST | `/probe/heartbeat` | JWT | Aggiorna stato + metriche |
| POST | `/probe/rotate-keys` | TenantAdmin+ | Rotazione chiavi crittografiche |
| GET | `/probes` | JWT | Lista probe del tenant |
| GET | `/probes/<id>` | JWT | Dettaglio probe |
| POST | `/probe-tokens` | TenantAdmin+ | Genera token registrazione |
| GET | `/probe-tokens` | TenantAdmin+ | Lista token |

### Task

| Metodo | Endpoint | Accesso | Descrizione |
|--------|----------|---------|-------------|
| GET | `/tasks` | JWT | Lista task |
| POST | `/tasks` | Operator+ | Crea task |
| GET | `/tasks/<id>` | JWT | Dettaglio task |
| POST | `/tasks/<id>/assign` | TenantAdmin+ | Assegna task a probe |
| DELETE | `/tasks/<id>` | TenantAdmin+ | Cancella task |
| GET | `/probe/<id>/tasks` | JWT | Task pendenti per la probe |
| POST | `/probe/<id>/tasks/<aid>/accept` | JWT | Probe accetta task |
| POST | `/probe/<id>/tasks/<aid>/result` | JWT | Probe invia risultato |

### Telemetria

| Metodo | Endpoint | Descrizione |
|--------|----------|-------------|
| POST | `/telemetry/devices` | Ingest device inventory |
| GET | `/telemetry/devices` | Lista device scoperte |
| POST | `/telemetry/services` | Ingest service inventory |
| POST | `/telemetry/wifi` | Ingest WiFi scan |
| POST | `/telemetry/ble` | Ingest BLE scan |

### Accounting

| Metodo | Endpoint | Descrizione |
|--------|----------|-------------|
| GET | `/accounting/daily?date=YYYY-MM-DD` | Riepilogo giornaliero |
| GET | `/accounting/monthly?year=&month=` | Riepilogo mensile |
| GET | `/accounting/usage` | Lista record uso |

### Audit

| Metodo | Endpoint | Accesso | Descrizione |
|--------|----------|---------|-------------|
| GET | `/audit` | TenantAdmin+ | Log audit (scoped) |
| GET | `/audit/user/<id>` | SuperAdmin | Audit per utente |

---

## Sistema Crittografico

Il protocollo di provisioning non memorizza mai segreti condivisi.

### Algoritmi

- **X25519** — Diffie-Hellman key exchange (ECDH su Curve25519)
- **Ed25519** — Firma digitale per autenticazione identità
- **HKDF-SHA256** — Derivazione di 3 chiavi da 96 byte di materiale crittografico
- **AES-256-GCM** — Cifratura autenticata per payload sensibili

### Chiavi Derivate (mai persistite)

```
HKDF(shared_secret, salt, info="soc-seattle-probe-v1") → 96 bytes
  [0:32]  → session_key    (usata per sessione corrente)
  [32:64] → transport_key  (usata per cifrare dati in transito)
  [64:96] → rotation_key   (usata per autenticare richiesta rotazione)
```

### Cosa viene salvato in DB

```
probes:
  public_sign_key              ← Ed25519 pub della probe
  public_exchange_key          ← X25519 pub della probe
  server_sign_public_key       ← Ed25519 pub del server (per questa probe)
  server_exchange_public_key   ← X25519 pub del server (per questa probe)
  server_side_fingerprint      ← SHA-256(all 4 public keys)
```

Mai memorizzati: chiave privata server, shared secret, session_key, transport_key, rotation_key.

---

## RBAC

| Ruolo | Permessi |
|-------|---------|
| **SuperAdmin** | Tutto (bypass di tutti i check) |
| **TenantAdmin** | CRUD utenti propri, token probe, task, audit, accounting del proprio tenant |
| **Operator** | Lettura probe/task/telemetry, creazione task autorizzati |
| **ReadOnly** | Sola lettura di probe, task, telemetry, audit, accounting |

---

## Test

```bash
# In-memory SQLite — no database esterno richiesto
pytest

# Con report coverage
pytest --cov=app --cov-report=html

# Solo una categoria
pytest tests/test_auth.py -v
```

Copertura target: **≥ 75%**.

---

## Deploy

### Vercel

```bash
vercel --prod
```

Variabili d'ambiente da configurare su Vercel Dashboard:
- `SECRET_KEY`
- `JWT_SECRET_KEY`
- `DATABASE_URL` (NeonDB connection string)
- `FLASK_ENV=production`
- `FORCE_HTTPS=true`

### NeonDB

1. Creare un progetto su [neon.tech](https://neon.tech)
2. Copiare la connection string nel formato `postgresql://user:pass@host/dbname?sslmode=require`
3. Impostare `DATABASE_URL` nelle variabili d'ambiente

### Esecuzione migrazioni in produzione

```bash
flask --app app db upgrade
python seed.py
```

---

## Struttura del Progetto

```
server/
├── app/
│   ├── __init__.py           # Application factory
│   ├── extensions.py         # db singleton
│   ├── logging_config.py     # structlog JSON
│   ├── api/
│   │   └── v1/               # REST API blueprints
│   ├── auth/                 # JWT, Argon2id, RBAC, MFA
│   ├── crypto/               # X25519/Ed25519/AES-GCM/HKDF
│   ├── middleware/           # Correlation ID, tenant isolation, audit
│   ├── models/               # SQLAlchemy models (tutti con tenant_id)
│   ├── repositories/         # Data access layer (auto-filtered)
│   ├── services/             # Business logic
│   ├── tenants/              # Tenant context (g.tenant_id)
│   ├── web/                  # Server-rendered views
│   └── templates/            # AdminLTE 4 Jinja2 templates
├── migrations/               # Alembic
├── tests/                    # Pytest suite
├── app.py                    # WSGI entrypoint
├── config.py                 # Configuration classes
├── seed.py                   # Seed script (roles + SuperAdmin)
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── vercel.json
└── .env.example
```

---

## Probe Contract (per sviluppo futuro)

La futura probe Docker dovrà implementare:

1. **Registrazione** — `POST /api/v1/probe/register` con token `PRB-XXXXXXXXXXXX`
2. **Key Provisioning** — `POST /api/v1/probe/provision-keys` con chiavi X25519/Ed25519
3. **Autenticazione** — Login con credenziali probe → JWT, oppure autenticazione basata su firma Ed25519
4. **Heartbeat** — `POST /api/v1/probe/heartbeat` ogni N secondi con metriche opzionali
5. **Task polling** — `GET /api/v1/probe/<id>/tasks` per recuperare task assegnati
6. **Result submission** — `POST /api/v1/probe/<id>/tasks/<aid>/result`
7. **Telemetria** — `POST /api/v1/telemetry/{devices,services,wifi,ble}`
8. **Code locale persistente** — In caso di server irraggiungibile, la probe deve accodare localmente risultati e telemetria

Il codice della probe deve essere sviluppato e distribuito indipendentemente dal server.
