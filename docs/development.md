# Development guide

## Local setup (no containers)

```bash
python3.12 -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements/dev.txt
cp .env.example .env    # SCARLET_ENV=development, DATABASE_URL unset -> SQLite ./scarlet-dev.sqlite
export FLASK_APP=wsgi.py SCARLET_INITIAL_ADMIN_PASSWORD='Adm1n-Passw0rd-Str0ng!' SCARLET_CELERY_EAGER=true
flask db upgrade
flask scarlet seed --with-demo
flask run --debug --port 5000
```

`SCARLET_CELERY_EAGER=true` runs jobs synchronously inside the web process (no Redis needed).
For the full asynchronous stack use `docker compose --profile dev up -d --build` (PostgreSQL,
Redis, web, worker, beat, nginx, mock host).

## Mock host

`docker/mockhost` is an Oracle Linux 9 image with sshd and rootless Podman (port 2222, user
`scarlet`, password `scarlet-dev`, or set `MOCKHOST_AUTHORIZED_KEY`). Register it as a DEV host
with hostname `mockhost` (inside the compose network) and runtime PODMAN. Because the mock host is
`privileged` it is for development only.

## Tests

```bash
make test               # or: pytest
pytest tests/unit -q    # ~1 s
pytest -m "security"    # markers: unit, integration, security, e2e
```

The suite (149 tests) uses SQLite in memory, eager Celery and `FakeSSHClientFactory`
(`app/ssh/fake.py`), which simulates an Oracle Linux host with Podman: it understands the exact
commands SCARLET emits, keeps a virtual filesystem and container table, and can be told to fail a
command type (`state.fail_on["runtime.podman.run"] = (125, "…")`), return a health status or be
unreachable. Fixtures in `tests/conftest.py`: `app`, `admin_client`, `operator_client`,
`viewer_client`, `prod_operator_client`, `podman_host`, `prod_host`, `customer_api`,
`released_version`, helpers `make_host`, `make_application`, `build_example_package`,
`upload_package`.

## Code quality

```bash
make lint       # ruff + black --check
make format     # ruff --fix + black
make typecheck  # mypy (best effort)
```

Rules: no business logic in routes; every remote command through `RemoteCommand` builders or
adapters; every new input through `app/security/validators.py`; every state change audited;
secrets never logged/serialised; new settings added to `Config`, `.env.example`, and (if runtime
tunable) `SETTING_DEFINITIONS`.

## Adding a runtime adapter

1. Create `app/runtimes/<name>.py` subclassing `RuntimeAdapter`; implement detect/status/version/
   inspect/logs/health/install/start/stop/remove (restart/rollback/apply have defaults).
2. Register with `RuntimeFactory.register(...)` in `app/runtimes/factory.py`.
3. Add the value to `RuntimeType` and the manifest `runtime` literal, plus docs and tests
   (extend `FakeSSHClient` with the CLI behaviour).

## Adding a migration

```bash
FLASK_APP=wsgi.py flask db migrate -m "describe change"
FLASK_APP=wsgi.py flask db upgrade
```
Review the generated file (`render_as_batch` is enabled for SQLite compatibility). Never edit an
applied migration; add a new one.

## Front-end

AdminLTE 4.3.1 + Bootstrap 5 from jsdelivr (or vendored with `scripts/fetch-vendor-assets.sh`).
CSP forbids inline scripts: page behaviour lives in `app/static/js/pages/*.js` and is selected by
the `data-page` attribute; `app/static/js/scarlet.js` provides the API client (CSRF header), toasts,
the confirmation modal (PROD phrase/reason), operation polling and the generic data table.

## Project layout

See README. Services return ORM objects; the API serialises with `to_dict()`; the web layer renders
Jinja templates that load live data through the same JSON API.

## Release checklist

- tests green, lint clean, migration present for schema changes;
- `docs/APPLICATION_RELEASE_CONTRACT.md` updated when the manifest changes (bump `manifest_version`
  only for breaking changes);
- image built with `docker build -f docker/Dockerfile`, `SCARLET_VERSION`/`APP_VERSION` bumped.
