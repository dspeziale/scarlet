"""Tenant lifecycle service."""

from __future__ import annotations

import re

import structlog

from app.extensions import db
from app.middleware.audit_middleware import record_audit
from app.models.tenant import Tenant
from app.repositories.tenant_repo import TenantRepository

log = structlog.get_logger(__name__)


def _slugify(name: str) -> str:
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-")[:60]


class TenantService:
    def __init__(self) -> None:
        self._repo = TenantRepository()

    def create_tenant(self, name: str, plan: str = "free", max_probes: int = 5, description: str | None = None) -> Tenant:
        slug = _slugify(name)
        if self._repo.get_by_slug(slug):
            raise ValueError(f"Tenant with slug '{slug}' already exists")
        if self._repo.get_by_name(name):
            raise ValueError(f"Tenant '{name}' already exists")

        tenant = Tenant(name=name, slug=slug, plan=plan, max_probes=max_probes, description=description)
        self._repo.save(tenant)
        record_audit("tenant.create", resource_type="tenant", resource_id=tenant.id, payload={"name": name})
        db.session.commit()
        log.info("tenant_created", tenant_id=tenant.id, name=name)
        return tenant

    def update_tenant(self, tenant_id: str, **kwargs) -> Tenant:
        tenant = self._repo.get_by_id(tenant_id)
        if not tenant:
            raise ValueError("Tenant not found")
        for k, v in kwargs.items():
            if hasattr(tenant, k):
                setattr(tenant, k, v)
        record_audit("tenant.update", resource_type="tenant", resource_id=tenant_id, payload=kwargs)
        db.session.commit()
        return tenant

    def deactivate_tenant(self, tenant_id: str) -> Tenant:
        tenant = self._repo.get_by_id(tenant_id)
        if not tenant:
            raise ValueError("Tenant not found")
        tenant.is_active = False
        record_audit("tenant.deactivate", resource_type="tenant", resource_id=tenant_id)
        db.session.commit()
        log.info("tenant_deactivated", tenant_id=tenant_id)
        return tenant

    def get_tenant(self, tenant_id: str) -> Tenant:
        tenant = self._repo.get_by_id(tenant_id)
        if not tenant:
            raise ValueError("Tenant not found")
        return tenant

    def list_tenants(self, limit: int = 100, offset: int = 0) -> list[Tenant]:
        return self._repo.list_all(limit=limit, offset=offset)
