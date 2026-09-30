"""Applicazione FastAPI: health, version, API inventario, pagina HTML."""

from __future__ import annotations

import html
import logging
import secrets
import time
from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from scarlet.config import Settings, get_settings
from scarlet.db import check_database, get_session
from scarlet.logging_config import configure_logging
from scarlet.models import Application, Deployment
from scarlet.schemas import ApplicationOut, DeploymentIn, DeploymentOut

log = logging.getLogger("scarlet")

_settings = get_settings()
configure_logging(_settings.log_level, _settings.log_format)

app = FastAPI(
    title="Scarlet",
    version=_settings.app_version,
    docs_url="/api/docs",
    redoc_url=None,
    openapi_url="/api/openapi.json",
)

SettingsDep = Annotated[Settings, Depends(get_settings)]
SessionDep = Annotated[Session, Depends(get_session)]


# --------------------------------------------------------------------------- middleware
@app.middleware("http")
async def access_log(request: Request, call_next: Callable) -> Response:
    started = time.perf_counter()
    response = await call_next(request)
    duration_ms = round((time.perf_counter() - started) * 1000, 1)
    # Gli health check sono frequenti: li registriamo solo se falliscono.
    if request.url.path not in ("/health", "/ready") or response.status_code >= 400:
        log.info(
            "request",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": duration_ms,
                "client": request.client.host if request.client else None,
            },
        )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "no-store"
    return response


# --------------------------------------------------------------------------- health
@app.get("/health", tags=["health"])
def health(settings: SettingsDep) -> JSONResponse:
    """Liveness: il processo e' vivo e risponde. Nessuna dipendenza esterna."""
    if settings.simulate_unhealthy:
        return JSONResponse({"status": "unhealthy", "reason": "simulazione"}, status_code=503)
    return JSONResponse({"status": "ok"})


@app.get("/ready", tags=["health"])
def ready(settings: SettingsDep) -> JSONResponse:
    """Readiness: pronta a ricevere traffico (DB raggiungibile, schema allineato)."""
    checks = {"database": check_database()}
    ok = all(c["ok"] for c in checks.values()) and not settings.simulate_unhealthy
    body = {"status": "ready" if ok else "not-ready", "checks": checks}
    return JSONResponse(body, status_code=200 if ok else 503)


@app.get("/version", tags=["health"])
def version(settings: SettingsDep) -> dict[str, str]:
    return {
        "application": "scarlet",
        "version": settings.app_version,
        "commit": settings.app_commit,
        "build_time": settings.app_build_time,
        "image": settings.image,
        "environment": settings.environment,
    }


# --------------------------------------------------------------------------- API
def require_api_token(
    settings: SettingsDep,
    x_api_key: Annotated[str | None, Header()] = None,
) -> None:
    if not settings.api_token:
        raise HTTPException(status_code=503, detail="API token non configurato (SCARLET_API_TOKEN)")
    if not x_api_key or not secrets.compare_digest(x_api_key, settings.api_token):
        raise HTTPException(status_code=401, detail="API key mancante o non valida")


def _to_out(d: Deployment) -> DeploymentOut:
    return DeploymentOut(
        id=d.id,
        application=d.application.name,
        environment=d.environment,
        version=d.version,
        image=d.image,
        commit=d.commit,
        actor=d.actor,
        result=d.result,
        deployed_at=d.deployed_at,
    )


def _latest_by_env(session: Session, application: Application) -> dict[str, DeploymentOut]:
    current: dict[str, DeploymentOut] = {}
    for env in ("development", "production"):
        stmt = (
            select(Deployment)
            .where(
                Deployment.application_id == application.id,
                Deployment.environment == env,
                Deployment.result == "success",
            )
            .order_by(Deployment.deployed_at.desc(), Deployment.id.desc())
            .limit(1)
        )
        row = session.scalars(stmt).first()
        if row:
            current[env] = _to_out(row)
    return current


@app.get("/api/applications", response_model=list[ApplicationOut], tags=["inventory"])
def list_applications(session: SessionDep) -> list[ApplicationOut]:
    apps = session.scalars(select(Application).order_by(Application.name)).all()
    return [
        ApplicationOut(name=a.name, repository=a.repository, current=_latest_by_env(session, a))
        for a in apps
    ]


@app.get("/api/deployments", response_model=list[DeploymentOut], tags=["inventory"])
def list_deployments(
    session: SessionDep,
    application: Annotated[str | None, Query(max_length=64)] = None,
    environment: Annotated[str | None, Query(max_length=32)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
) -> list[DeploymentOut]:
    stmt = select(Deployment).join(Application)
    if application:
        stmt = stmt.where(Application.name == application)
    if environment:
        stmt = stmt.where(Deployment.environment == environment)
    stmt = stmt.order_by(Deployment.deployed_at.desc(), Deployment.id.desc()).limit(limit)
    return [_to_out(d) for d in session.scalars(stmt).all()]


@app.post(
    "/api/deployments",
    response_model=DeploymentOut,
    status_code=201,
    dependencies=[Depends(require_api_token)],
    tags=["inventory"],
)
def record_deployment(payload: DeploymentIn, session: SessionDep) -> DeploymentOut:
    application = session.scalars(
        select(Application).where(Application.name == payload.application)
    ).first()
    if application is None:
        application = Application(name=payload.application, repository=payload.repository)
        session.add(application)
        session.flush()
    elif payload.repository and application.repository != payload.repository:
        application.repository = payload.repository

    deployment = Deployment(
        application=application,
        environment=payload.environment,
        version=payload.version,
        image=payload.image,
        commit=payload.commit,
        actor=payload.actor,
        result=payload.result,
    )
    session.add(deployment)
    session.commit()
    session.refresh(deployment)
    log.info(
        "deployment registrato: %s %s %s (%s)",
        payload.application,
        payload.environment,
        payload.version,
        payload.result,
    )
    return _to_out(deployment)


# --------------------------------------------------------------------------- pagina HTML
_PAGE = """<!doctype html>
<html lang="it"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Scarlet - inventario rilasci</title>
<style>
 body{{font-family:system-ui,sans-serif;margin:2rem;color:#222}}
 table{{border-collapse:collapse;width:100%}} th,td{{border:1px solid #ccc;padding:.4rem .6rem;text-align:left}}
 th{{background:#f3f3f3}} .muted{{color:#777;font-size:.9rem}} code{{background:#f6f6f6;padding:0 .2rem}}
</style></head><body>
<h1>Scarlet <span class="muted">inventario dei rilasci</span></h1>
<p class="muted">Versione {version} &middot; commit <code>{commit}</code> &middot; ambiente {environment}</p>
<table><thead><tr><th>Applicazione</th><th>Development</th><th>Production</th></tr></thead>
<tbody>{rows}</tbody></table>
<p class="muted">API: <a href="/api/docs">/api/docs</a></p>
</body></html>"""


def _cell(d: DeploymentOut | None) -> str:
    if d is None:
        return "<td class='muted'>-</td>"
    when = d.deployed_at.strftime("%Y-%m-%d %H:%M")
    return (
        f"<td><strong>{html.escape(d.version)}</strong><br>"
        f"<span class='muted'>{html.escape(d.image)}</span><br>"
        f"<span class='muted'>{when} &middot; {html.escape(d.actor)}</span></td>"
    )


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def index(session: SessionDep, settings: SettingsDep) -> str:
    rows = []
    for a in list_applications(session):
        rows.append(
            f"<tr><td>{html.escape(a.name)}</td>"
            f"{_cell(a.current.get('development'))}{_cell(a.current.get('production'))}</tr>"
        )
    if not rows:
        rows.append("<tr><td colspan='3' class='muted'>Nessun deployment registrato</td></tr>")
    return _PAGE.format(
        version=html.escape(settings.app_version),
        commit=html.escape(settings.app_commit),
        environment=html.escape(settings.environment),
        rows="".join(rows),
    )
