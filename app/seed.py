"""Database seeding: environments, RBAC, admin user and optional demo data.

No SSH passwords or private keys are ever seeded. Demo hosts are created
without credentials; operators add them through the UI.
"""

from __future__ import annotations

import os
from typing import Any

from flask import current_app

from app.audit import audit
from app.extensions import db
from app.models import Application, ApplicationVersion, Environment, HostGroup, TargetHost
from app.models.enums import EnvironmentType, HealthCheckType, RuntimeType
from app.repositories import (
    ApplicationRepository,
    EnvironmentRepository,
    HostGroupRepository,
    HostRepository,
    UserRepository,
)
from app.security.rbac import ROLE_ADMIN
from app.services.user_service import UserService

ENVIRONMENTS = [
    {
        "code": EnvironmentType.DEV.value,
        "name": "Development",
        "description": "Development and test hosts",
        "is_production": False,
        "color": "success",
        "sort_order": 10,
        "require_confirmation": False,
        "require_approval": False,
        "allow_rollback": True,
        "max_parallel_deployments": 3,
    },
    {
        "code": EnvironmentType.PROD.value,
        "name": "Production",
        "description": "Production hosts: confirmation required",
        "is_production": True,
        "color": "danger",
        "sort_order": 20,
        "require_confirmation": True,
        "require_approval": False,
        "allow_rollback": True,
        "max_parallel_deployments": 1,
    },
]


def seed_environments() -> int:
    repo = EnvironmentRepository()
    created = 0
    for spec in ENVIRONMENTS:
        if repo.by_code(spec["code"]) is None:
            db.session.add(Environment(**spec))
            created += 1
    db.session.commit()
    return created


def seed_admin() -> bool:
    users = UserRepository()
    if users.by_username("admin") is not None:
        return False
    password = os.environ.get("SCARLET_INITIAL_ADMIN_PASSWORD") or current_app.config.get(
        "SCARLET_INITIAL_ADMIN_PASSWORD"
    )
    if not password:
        return False
    UserService().create_user(
        username="admin",
        password=password,
        roles=[ROLE_ADMIN],
        full_name="Administrator",
        must_change_password=True,
    )
    return True


def seed_demo() -> dict[str, Any]:
    envs = EnvironmentRepository()
    hosts = HostRepository()
    apps = ApplicationRepository()
    groups = HostGroupRepository()
    dev = envs.by_code("DEV")
    prod = envs.by_code("PROD")
    summary: dict[str, Any] = {"hosts": 0, "groups": 0, "applications": 0, "versions": 0}
    if hosts.by_name("dev-app-01") is None:
        db.session.add(
            TargetHost(
                name="dev-app-01",
                hostname="dev-app-01.example.internal",
                ip_address="10.10.1.21",
                ssh_port=22,
                ssh_username="scarlet",
                environment_id=dev.id,
                runtime_type=RuntimeType.PODMAN.value,
                description="Demo DEV host (add an SSH credential to use it)",
            )
        )
        summary["hosts"] += 1
    if hosts.by_name("prod-app-01") is None:
        db.session.add(
            TargetHost(
                name="prod-app-01",
                hostname="prod-app-01.example.internal",
                ip_address="10.20.1.21",
                ssh_port=22,
                ssh_username="scarlet",
                environment_id=prod.id,
                runtime_type=RuntimeType.PODMAN.value,
                description="Demo PROD host (add an SSH credential to use it)",
            )
        )
        summary["hosts"] += 1
    db.session.commit()
    for name, env in (("DEV-API", dev), ("PROD-API", prod)):
        if groups.by_name(name) is None:
            group = HostGroup(
                name=name, description=f"{env.name} API servers", environment_id=env.id
            )
            group.hosts = [h for h in hosts.all() if h.environment_id == env.id]
            db.session.add(group)
            summary["groups"] += 1
    db.session.commit()
    demo_apps = [
        {
            "name": "Customer API",
            "code": "customer-api",
            "description": "Customer master data REST API",
            "owner": "Team Customer",
            "runtime_type": RuntimeType.PODMAN.value,
            "default_port": 8080,
            "healthcheck_type": HealthCheckType.HTTP.value,
            "healthcheck_url": "/health",
            "healthcheck_port": 8080,
            "allowed_environments": ["DEV", "PROD"],
            "allowed_runtimes": ["PODMAN", "DOCKER"],
            "versions": ["1.0.0", "1.1.0", "1.2.0", "2.0.0"],
        },
        {
            "name": "Billing Worker",
            "code": "billing-worker",
            "description": "Asynchronous billing batch worker",
            "owner": "Team Finance",
            "runtime_type": RuntimeType.DOCKER.value,
            "default_port": None,
            "healthcheck_type": HealthCheckType.CONTAINER_STATUS.value,
            "allowed_environments": ["DEV"],
            "allowed_runtimes": ["DOCKER", "PODMAN"],
            "versions": ["0.9.0", "1.0.0"],
        },
    ]
    for spec in demo_apps:
        versions = spec.pop("versions")
        app = apps.by_code(spec["code"])
        if app is None:
            app = Application(**spec)
            db.session.add(app)
            db.session.flush()
            summary["applications"] += 1
        for version in versions:
            exists = db.session.execute(
                db.select(ApplicationVersion).where(
                    ApplicationVersion.application_id == app.id,
                    ApplicationVersion.version == version,
                )
            ).scalar_one_or_none()
            if exists:
                continue
            major, minor, patch = (int(p) for p in version.split("."))
            manifest = {
                "manifest_version": 1,
                "application": app.code,
                "version": version,
                "runtime": app.runtime_type.lower(),
                "image": {
                    "name": f"registry.example.internal/{app.code}",
                    "tag": version,
                    "pull_policy": "if-not-present",
                },
                "ports": (
                    [{"container": 8080, "host": 8080, "protocol": "tcp"}]
                    if app.default_port
                    else []
                ),
                "healthcheck": {
                    "type": app.healthcheck_type.lower(),
                    "path": app.healthcheck_url or "/health",
                    "port": app.healthcheck_port,
                    "expected_status": 200,
                    "timeout": 5,
                    "retries": 5,
                    "interval": 3,
                },
                "deployment": {
                    "strategy": "recreate",
                    "restart_policy": "unless-stopped",
                    "replicas": 1,
                },
                "resources": {"cpu": "1", "memory": "512Mi"},
            }
            db.session.add(
                ApplicationVersion(
                    application_id=app.id,
                    version=version,
                    major=major,
                    minor=minor,
                    patch=patch,
                    runtime_type=app.runtime_type,
                    image_name=manifest["image"]["name"],
                    image_tag=version,
                    manifest=manifest,
                    checksum_sha256=("%064x" % (hash((app.code, version)) & ((1 << 256) - 1))),
                    release_notes=f"Demo release {version} (metadata only, no artifact)",
                    is_active=True,
                )
            )
            summary["versions"] += 1
    db.session.commit()
    audit.record("SEED_DEMO_DATA", entity_type="System", details=summary)
    for host in hosts.all():
        audit.record(
            "HOST_CREATED",
            target=host,
            entity_type="TargetHost",
            entity_id=host.id,
            details={"seed": True},
        )
    return summary


def seed_all(with_demo: bool = False) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    summary["environments_created"] = seed_environments()
    UserService().sync_permissions_and_roles()
    summary["rbac"] = "synchronized"
    summary["admin_created"] = seed_admin()
    if not summary["admin_created"] and UserRepository().by_username("admin") is None:
        summary["admin_created"] = "SKIPPED: set SCARLET_INITIAL_ADMIN_PASSWORD"
    if with_demo:
        if current_app.config.get("SCARLET_ENV") == "production":
            summary["demo"] = "refused in production"
        else:
            summary["demo"] = seed_demo()
    return summary
