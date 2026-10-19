# API REST

- Base path: `/api/v1`. Specifica OpenAPI 3: [openapi.json](openapi.json) (servita anche su `/api/v1/openapi.json`;
  Swagger UI su `/api/docs` solo con `environment: development`). Rigenerazione dalla radice del repository:
  ```bash
  PYTHONPATH=backend backend/.venv/Scripts/python -c "import json; from pkm.config import Settings; from pkm.main import create_app; s=Settings(mode='demo', environment='development', database={'path': 'var/openapi/pkm.db'}, backup={'directory': 'var/openapi/bk'}); print(json.dumps(create_app(s, start_background=False).openapi(), indent=2))" > docs/api/openapi.json
  ```
- Formato: JSON; ogni risposta include `X-Request-ID` e `X-PKM-Mode` (`live`/`demo`).

## Autenticazione

```bash
# 1. login: imposta il cookie di sessione e restituisce il token CSRF
curl -sk -c cookies -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"..."}' https://pkm:8443/api/v1/auth/login
# {"user": {...}, "permissions": [...], "csrfToken": "…", "expiresAt": "…"}

# 2. lettura
curl -sk -b cookies https://pkm:8443/api/v1/cluster/overview

# 3. scrittura: X-CSRF-Token obbligatorio
curl -sk -b cookies -H "X-CSRF-Token: $CSRF" -H 'Content-Type: application/json' \
  -d '{"replicas":3}' https://pkm:8443/api/v1/k8s/deployments/production/web-prod/scale
```

Il cookie è `__Host-pkm_session` con TLS (o proxy fidato), `pkm_session` in HTTP. Il token CSRF è restituito anche da
`GET /auth/me`. Se presente, l'header `Origin` deve coincidere con `Host`. Le risorse cluster-scoped usano `_` come
namespace (`/k8s/nodes/_/node-01`).

## Errori

```json
{"error": {"code": "k8s_forbidden", "message": "the Kubernetes account used by Scarlet is not allowed to do this",
           "params": {"status": 403, "reason": "Forbidden"}, "details": "<messaggio dell'API server>", "requestId": "…"}}
```

| HTTP | Codici tipici |
|---|---|
| 400 | `bad_request` |
| 401 | `unauthorized` |
| 403 | `forbidden` (RBAC Scarlet, CSRF), `k8s_forbidden` |
| 404 | `not_found`, `k8s_not_found`, `podman_not_found` |
| 409 | `conflict`, `k8s_conflict` |
| 422 | `validation_failed` (`params.errors[]` con `field`/`message`, righe YAML), `k8s_invalid` (`params.causes[]`) |
| 428 | `confirmation_required` (`params.expected` = valore da inviare in `confirm`) |
| 429 | `rate_limited` (`params.retryAfter`) |
| 501 | `not_supported`, `k8s_unsupported` |
| 502/503/504 | `k8s_unavailable`, `k8s_not_configured`, `k8s_auth_failed`, `k8s_timeout`, `podman_*`, `metrics_unavailable`, `internal_error` (500) |

## Server-Sent Events

- `GET /api/v1/stream`: `event: hello` con i conteggi, poi messaggi `{"type":"notifications","counts":{…}}`; commenti keepalive ogni 20 s.
- `GET /api/v1/k8s/pods/{namespace}/{name}/logs/stream?container=&tail=`: messaggi `data: ["<timestamp RFC3339> <riga>", …]`,
  eventi `open`, `end`, `limit` (`{"reason":"duration"|"lines"}`), `error` (`{"code","message"}`). Richiede `logs.read`.

## Operazioni lunghe

`POST /k8s/nodes/_/{name}/drain` e `POST /backups` restituiscono `{"operation": {...}}`; stato con
`GET /operations/{id}` (`running|succeeded|failed|cancelled`, `steps[]`, `result`, `error`), annullamento con
`POST /operations/{id}/cancel`.

## Endpoint pubblici

`GET /healthz`, `GET /readyz`, `GET /api/v1/system/info`, `POST /api/v1/auth/login`, `/api/v1/setup/*` (header `X-Setup-Token`, solo finché non esistono utenti).
