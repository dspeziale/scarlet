"""Security (users, roles, audit), settings, backup and maintenance."""

from __future__ import annotations

import csv
import io
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from ..context import AppContext
from ..errors import ConfirmationRequired, NotFound
from ..runtime_settings import EDITABLE
from ..security.rbac import ROLE_PERMISSIONS, Perm
from ..security.users import Session
from .deps import Audited, audited, get_ctx, require

router = APIRouter(tags=["administration"])


# ---------------------------------------------------------------- users
class UserCreate(BaseModel):
    username: str = Field(min_length=2, max_length=63)
    password: str = Field(min_length=1, max_length=256)
    role: Literal["admin", "operator", "viewer"]
    display_name: str = Field("", max_length=120)
    email: str = Field("", max_length=200)
    language: Literal["it", "en"] = "it"
    must_change_password: bool = True


class UserUpdate(BaseModel):
    role: Literal["admin", "operator", "viewer"] | None = None
    display_name: str | None = Field(None, max_length=120)
    email: str | None = Field(None, max_length=200)
    active: bool | None = None
    language: Literal["it", "en"] | None = None


class PasswordReset(BaseModel):
    password: str = Field(min_length=1, max_length=256)
    must_change_password: bool = True


@router.get("/users")
def list_users(_: Session = Depends(require(Perm.USERS_MANAGE)), ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:
    return {"items": [u.public() for u in ctx.users.list()]}


@router.post("/users")
def create_user(body: UserCreate, _: Session = Depends(require(Perm.USERS_MANAGE)), ctx: AppContext = Depends(get_ctx),
                audit: Audited = Depends(audited)) -> dict[str, Any]:  # fmt: skip
    user = ctx.users.create(body.username, body.password, body.role, display_name=body.display_name, email=body.email,
                            language=body.language, must_change_password=body.must_change_password)  # fmt: skip
    audit("user.create", kind="User", name=user.username, detail={"role": user.role})
    return {"user": user.public()}


@router.patch("/users/{user_id}")
def update_user(user_id: int, body: UserUpdate, session: Session = Depends(require(Perm.USERS_MANAGE)),
                ctx: AppContext = Depends(get_ctx), audit: Audited = Depends(audited)) -> dict[str, Any]:  # fmt: skip
    before = ctx.users.get(user_id)
    user = ctx.users.update(user_id, actor_id=session.user.id, **body.model_dump(exclude_none=True))
    changes = {k: {"from": getattr(before, k), "to": v} for k, v in body.model_dump(exclude_none=True).items()
               if getattr(before, k) != v}  # fmt: skip
    audit("user.update", kind="User", name=user.username, detail={"changes": changes})
    return {"user": user.public()}


@router.post("/users/{user_id}/password")
def reset_password(user_id: int, body: PasswordReset, _: Session = Depends(require(Perm.USERS_MANAGE)),
                   ctx: AppContext = Depends(get_ctx), audit: Audited = Depends(audited)) -> dict[str, Any]:  # fmt: skip
    ctx.users.set_password(user_id, body.password, must_change=body.must_change_password)
    user = ctx.users.get(user_id)
    audit("user.password_reset", kind="User", name=user.username)
    return {"user": user.public()}


@router.post("/users/{user_id}/unlock")
def unlock_user(user_id: int, _: Session = Depends(require(Perm.USERS_MANAGE)), ctx: AppContext = Depends(get_ctx),
                audit: Audited = Depends(audited)) -> dict[str, Any]:  # fmt: skip
    ctx.users.unlock(user_id)
    user = ctx.users.get(user_id)
    audit("user.unlock", kind="User", name=user.username)
    return {"user": user.public()}


@router.delete("/users/{user_id}")
def delete_user(user_id: int, confirm: str | None = Query(None, max_length=64),
                session: Session = Depends(require(Perm.USERS_MANAGE)), ctx: AppContext = Depends(get_ctx),
                audit: Audited = Depends(audited)) -> dict[str, Any]:  # fmt: skip
    user = ctx.users.get(user_id)
    if confirm != user.username:
        raise ConfirmationRequired(f"type '{user.username}' to confirm", params={"expected": user.username, "risk": "high"})
    ctx.users.delete(user_id, actor_id=session.user.id)
    audit("user.delete", kind="User", name=user.username)
    return {"ok": True}


@router.get("/rbac/roles")
def roles(_: Session = Depends(require(Perm.CLUSTER_READ))) -> dict[str, Any]:
    return {
        "roles": [{"id": r.value, "permissions": sorted(p.value for p in perms)} for r, perms in ROLE_PERMISSIONS.items()],
        "permissions": sorted(p.value for p in Perm),
    }


# ---------------------------------------------------------------- audit
def _audit_filters(q: str | None, username: str | None, action: str | None, result: str | None,
                   namespace: str | None, kind: str | None, since: str | None, until: str | None) -> dict[str, Any]:  # fmt: skip
    return {"q": q, "username": username, "action": action, "result": result, "namespace": namespace, "kind": kind,
            "since": since, "until": until}  # fmt: skip


@router.get("/audit")
def audit_log(q: str | None = Query(None, max_length=200), username: str | None = Query(None, max_length=64),
              action: str | None = Query(None, max_length=100), result: Literal["success", "failure", "denied"] | None = None,
              namespace: str | None = Query(None, max_length=63), kind: str | None = Query(None, max_length=64),
              since: str | None = Query(None, max_length=40), until: str | None = Query(None, max_length=40),
              limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0),
              _: Session = Depends(require(Perm.AUDIT_READ)), ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:  # fmt: skip
    res = ctx.audit.search(**_audit_filters(q, username, action, result, namespace, kind, since, until),
                           limit=limit, offset=offset)  # fmt: skip
    res["actions"] = ctx.audit.distinct_actions()
    res["retentionDays"] = ctx.settings.audit.retention_days
    return res


@router.get("/audit/export.csv")
def audit_export(q: str | None = Query(None, max_length=200), username: str | None = Query(None, max_length=64),
                 action: str | None = Query(None, max_length=100), result: str | None = Query(None, max_length=10),
                 namespace: str | None = Query(None, max_length=63), kind: str | None = Query(None, max_length=64),
                 since: str | None = Query(None, max_length=40), until: str | None = Query(None, max_length=40),
                 _: Session = Depends(require(Perm.AUDIT_READ)), ctx: AppContext = Depends(get_ctx),
                 audit: Audited = Depends(audited)) -> StreamingResponse:  # fmt: skip
    res = ctx.audit.search(**_audit_filters(q, username, action, result, namespace, kind, since, until), limit=500)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "ts", "username", "action", "resource_kind", "resource_name", "namespace", "result", "ip",
                "request_id", "detail"])  # fmt: skip
    for r in res["items"]:
        w.writerow([r["id"], r["ts"], r["username"], r["action"], r["resource_kind"], r["resource_name"],
                    r["namespace"], r["result"], r["ip"], r["request_id"], r["detail"]])  # fmt: skip
    audit("audit.export", detail={"rows": len(res["items"])})
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": 'attachment; filename="pkm-audit.csv"'})  # fmt: skip


@router.get("/audit/{entry_id}")
def audit_entry(entry_id: int, _: Session = Depends(require(Perm.AUDIT_READ)), ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:
    entry = ctx.audit.get(entry_id)
    if entry is None:
        raise NotFound("audit entry not found")
    return entry


# ---------------------------------------------------------------- settings
@router.get("/settings")
def get_settings(_: Session = Depends(require(Perm.SETTINGS_READ)), ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:
    s = ctx.settings
    return {"effective": ctx.runtime.describe(), "editable": {k: sorted(v) for k, v in EDITABLE.items()},
            "readonly": {"mode": s.mode, "environment": s.environment, "configFile": s.config_file,
                         "server": {"host": s.server.host, "port": s.server.port, "tls": s.server.tls_enabled,
                                    "tlsCert": s.server.tls_cert, "trustedProxies": s.server.trusted_proxies},
                         "database": s.database.path, "logFile": s.logging.file,
                         "backupDirectory": s.backup.directory, "cookieSecure": s.cookie_secure}}  # fmt: skip


@router.put("/settings/{section}")
def put_settings(section: str, values: dict[str, Any], session: Session = Depends(require(Perm.SETTINGS_MANAGE)),
                 ctx: AppContext = Depends(get_ctx), audit: Audited = Depends(audited)) -> dict[str, Any]:  # fmt: skip
    before = ctx.runtime.describe().get(section, {})
    try:
        ctx.runtime.update(section, values, session.user.username)
    except Exception as exc:
        audit("settings.update", result="failure", kind="Settings", name=section, detail={"error": str(exc)[:300]})
        raise
    ctx.apply_settings(section)
    changes = {k: {"from": before.get(k, {}).get("value"), "to": v} for k, v in values.items()}
    audit("settings.update", kind="Settings", name=section, detail={"changes": changes})
    return {"effective": ctx.runtime.describe()}


@router.delete("/settings/{section}")
def reset_settings(section: str, session: Session = Depends(require(Perm.SETTINGS_MANAGE)),
                   ctx: AppContext = Depends(get_ctx), audit: Audited = Depends(audited)) -> dict[str, Any]:  # fmt: skip
    ctx.runtime.reset(section, session.user.username)
    ctx.apply_settings(section)
    audit("settings.reset", kind="Settings", name=section)
    return {"effective": ctx.runtime.describe()}


# ---------------------------------------------------------------- backup
class BackupBody(BaseModel):
    include_manifests: bool | None = None


@router.get("/backups")
def list_backups(_: Session = Depends(require(Perm.BACKUP_READ)), ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:
    return {"items": ctx.backups.list(), "directory": ctx.settings.backup.directory,
            "retentionCount": ctx.settings.backup.retention_count,
            "includeManifests": ctx.settings.backup.include_manifests}  # fmt: skip


@router.post("/backups")
def create_backup(body: BackupBody, session: Session = Depends(require(Perm.BACKUP_MANAGE)),
                  ctx: AppContext = Depends(get_ctx), audit: Audited = Depends(audited)) -> dict[str, Any]:  # fmt: skip
    include = ctx.settings.backup.include_manifests if body.include_manifests is None else body.include_manifests

    def run(op):  # type: ignore[no-untyped-def]
        res = ctx.backups.create(trigger="manual", user=session.user.username, include_manifests=include,
                                 k8s=ctx.k8s if include else None, progress=op.progress)  # fmt: skip
        removed = ctx.backups.apply_retention(ctx.settings.backup.retention_count)
        return {"backup": res, "removedByRetention": removed}

    from .deps import audit_ctx

    actx = audit_ctx(audit.request, session)

    def done(op):  # type: ignore[no-untyped-def]
        ctx.audit.record(actx, "backup.create", result="success" if op.status == "succeeded" else "failure",
                         kind="Backup", name=((op.result or {}).get("backup") or {}).get("filename", ""),
                         detail={"includeManifests": include, "error": op.error})  # fmt: skip

    op = ctx.operations.start("backup", "pkm", session.user.username, run, done)
    return {"operation": op.public()}


@router.post("/backups/{filename}/verify")
def verify_backup(filename: str, _: Session = Depends(require(Perm.BACKUP_MANAGE)), ctx: AppContext = Depends(get_ctx),
                  audit: Audited = Depends(audited)) -> dict[str, Any]:  # fmt: skip
    res = ctx.backups.verify(filename)
    audit("backup.verify", result="success" if res["ok"] else "failure", kind="Backup", name=filename)
    return res


@router.get("/backups/{filename}/download")
def download_backup(filename: str, _: Session = Depends(require(Perm.BACKUP_MANAGE)), ctx: AppContext = Depends(get_ctx),
                    audit: Audited = Depends(audited)) -> FileResponse:  # fmt: skip
    path = ctx.backups.file_path(filename)
    audit("backup.download", kind="Backup", name=filename)
    return FileResponse(path, media_type="application/gzip", filename=filename)


@router.delete("/backups/{filename}")
def delete_backup(filename: str, confirm: str | None = Query(None, max_length=100),
                  _: Session = Depends(require(Perm.BACKUP_MANAGE)), ctx: AppContext = Depends(get_ctx),
                  audit: Audited = Depends(audited)) -> dict[str, Any]:  # fmt: skip
    if confirm != filename:
        raise ConfirmationRequired("type the file name to confirm", params={"expected": filename, "risk": "high"})
    ctx.backups.delete(filename)
    audit("backup.delete", kind="Backup", name=filename)
    return {"ok": True}


# ---------------------------------------------------------------- maintenance
@router.post("/maintenance/housekeeping")
def housekeeping(_: Session = Depends(require(Perm.MAINTENANCE)), ctx: AppContext = Depends(get_ctx),
                 audit: Audited = Depends(audited)) -> dict[str, Any]:  # fmt: skip
    res = ctx.housekeeping(force=True)
    audit("maintenance.housekeeping", detail=res)
    return res


@router.post("/maintenance/cache/clear")
def clear_cache(_: Session = Depends(require(Perm.MAINTENANCE)), ctx: AppContext = Depends(get_ctx),
                audit: Audited = Depends(audited)) -> dict[str, Any]:  # fmt: skip
    ctx.k8s.invalidate()
    audit("maintenance.cache_clear")
    return {"ok": True}


@router.post("/maintenance/database/optimize")
def optimize_db(_: Session = Depends(require(Perm.MAINTENANCE)), ctx: AppContext = Depends(get_ctx),
                audit: Audited = Depends(audited)) -> dict[str, Any]:  # fmt: skip
    with ctx.db.connect() as c:
        integrity = c.execute("PRAGMA integrity_check").fetchone()[0]
        c.execute("PRAGMA optimize")
        c.execute("VACUUM")
    audit("maintenance.db_optimize", detail={"integrity": integrity})
    return {"integrity": integrity}
