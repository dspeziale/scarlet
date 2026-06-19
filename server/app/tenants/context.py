"""Thread-local tenant context — every DB query is filtered through this."""

from __future__ import annotations

from flask import g


def set_tenant_id(tenant_id: str | None) -> None:
    g.tenant_id = tenant_id


def get_tenant_id() -> str | None:
    return getattr(g, "tenant_id", None)


def require_tenant_id() -> str:
    tid = get_tenant_id()
    if not tid:
        raise RuntimeError("Tenant context not set")
    return tid
