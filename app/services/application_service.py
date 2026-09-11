"""Application management: CRUD, versions, target rules and compatibility checks."""

from __future__ import annotations

import shlex
from typing import Any

from app.audit import audit
from app.errors import ConflictError, ValidationError
from app.extensions import db
from app.models.application import Application, ApplicationVersion
from app.models.enums import EnvironmentType, HealthCheckType, RuntimeType
from app.models.host import TargetHost
from app.repositories import (
    ApplicationRepository,
    DeploymentRepository,
    EnvironmentRepository,
    HostGroupRepository,
    InstanceRepository,
    VersionRepository,
)
from app.security.validators import validate_app_code, validate_int_range, validate_url_path


class ApplicationService:
    def __init__(self) -> None:
        self.apps = ApplicationRepository()
        self.versions = VersionRepository()
        self.instances = InstanceRepository()
        self.environments = EnvironmentRepository()
        self.groups = HostGroupRepository()
        self.deployments = DeploymentRepository()

    # --- validation -----------------------------------------------------------------------
    def _validate_payload(self, data: dict[str, Any], *, partial: bool = False) -> dict[str, Any]:
        out: dict[str, Any] = {}
        errors: dict[str, list[str]] = {}
        if "name" in data or not partial:
            name = str(data.get("name", "")).strip()
            if not 2 <= len(name) <= 128:
                errors["name"] = ["2-128 characters."]
            out["name"] = name
        if "code" in data or not partial:
            try:
                out["code"] = validate_app_code(str(data.get("code", "")))
            except ValidationError as exc:
                errors.update(exc.errors)
        if "runtime_type" in data or not partial:
            rt = RuntimeType.parse(data.get("runtime_type"))
            if rt is None or rt == RuntimeType.NONE:
                errors["runtime_type"] = ["Must be DOCKER, PODMAN or KUBERNETES."]
            else:
                out["runtime_type"] = rt.value
        for key, limit in (
            ("description", 4000),
            ("owner", 128),
            ("repository", 255),
            ("artifact_type", 32),
        ):
            if key in data and data[key] is not None:
                out[key] = str(data[key])[:limit]
        if "default_port" in data:
            port = data.get("default_port")
            out["default_port"] = (
                validate_int_range(port, field="default_port", minimum=1, maximum=65535)
                if port not in (None, "")
                else None
            )
        if "healthcheck_type" in data:
            hc = HealthCheckType.parse(data.get("healthcheck_type"))
            if hc is None:
                errors["healthcheck_type"] = [
                    f"Must be one of {', '.join(HealthCheckType.values())}."
                ]
            else:
                out["healthcheck_type"] = hc.value
        if "healthcheck_url" in data:
            url = (data.get("healthcheck_url") or "").strip()
            if url:
                try:
                    url = validate_url_path(url)
                except ValidationError as exc:
                    errors["healthcheck_url"] = exc.errors.get("path", ["Invalid path."])
            out["healthcheck_url"] = url or None
        if "healthcheck_command" in data:
            cmd = (data.get("healthcheck_command") or "").strip()
            if cmd:
                try:
                    parts = shlex.split(cmd)
                except ValueError:
                    parts = []
                if not parts or len(parts) > 32 or any(ch in cmd for ch in "\n\r\x00;|&$`"):
                    errors["healthcheck_command"] = ["Invalid command (no shell metacharacters)."]
            out["healthcheck_command"] = cmd[:512] or None
        if "healthcheck_port" in data:
            port = data.get("healthcheck_port")
            out["healthcheck_port"] = (
                validate_int_range(port, field="healthcheck_port", minimum=1, maximum=65535)
                if port not in (None, "")
                else None
            )
        for key, lo, hi in (
            ("healthcheck_expected_status", 100, 599),
            ("healthcheck_timeout", 1, 300),
            ("healthcheck_retries", 1, 50),
            ("healthcheck_interval", 0, 300),
        ):
            if key in data and data[key] not in (None, ""):
                try:
                    out[key] = validate_int_range(data[key], field=key, minimum=lo, maximum=hi)
                except ValidationError as exc:
                    errors.update(exc.errors)
        for key in ("enabled", "allow_hooks"):
            if key in data and data[key] is not None:
                out[key] = bool(data[key])
        if "allowed_environments" in data and data["allowed_environments"] is not None:
            envs = []
            for code in data["allowed_environments"]:
                code = str(code).upper()
                if self.environments.by_code(code) is None:
                    errors["allowed_environments"] = [f"Unknown environment {code}."]
                envs.append(code)
            out["allowed_environments"] = envs
        if "allowed_runtimes" in data and data["allowed_runtimes"] is not None:
            runtimes = []
            for rt in data["allowed_runtimes"]:
                parsed = RuntimeType.parse(rt)
                if parsed is None or parsed == RuntimeType.NONE:
                    errors["allowed_runtimes"] = [f"Invalid runtime {rt}."]
                else:
                    runtimes.append(parsed.value)
            out["allowed_runtimes"] = runtimes
        if "allowed_host_group_ids" in data and data["allowed_host_group_ids"] is not None:
            ids = []
            for gid in data["allowed_host_group_ids"]:
                if self.groups.get(int(gid)) is None:
                    errors["allowed_host_group_ids"] = [f"Unknown host group {gid}."]
                ids.append(int(gid))
            out["allowed_host_group_ids"] = ids
        if errors:
            raise ValidationError("Application data is invalid.", errors=errors)
        return out

    # --- CRUD -------------------------------------------------------------------------------
    def create(self, data: dict[str, Any], *, user=None) -> Application:
        payload = self._validate_payload(data)
        if self.apps.by_code(payload["code"]):
            raise ConflictError(f"An application with code '{payload['code']}' already exists.")
        app = Application(**payload)
        db.session.add(app)
        db.session.commit()
        audit.record(
            "APPLICATION_CREATED",
            user=user,
            application=app,
            entity_type="Application",
            entity_id=app.id,
            details={"code": app.code, "runtime_type": app.runtime_type},
        )
        return app

    def update(self, app: Application, data: dict[str, Any], *, user=None) -> Application:
        payload = self._validate_payload(data, partial=True)
        if "code" in payload and payload["code"] != app.code:
            if app.versions:
                raise ConflictError("The application code cannot change once versions exist.")
            if self.apps.by_code(payload["code"]):
                raise ConflictError("An application with this code already exists.")
        before = app.to_dict()
        for key, value in payload.items():
            setattr(app, key, value)
        db.session.commit()
        after = app.to_dict()
        changes = {
            k: {"before": before.get(k), "after": after.get(k)}
            for k in after
            if before.get(k) != after.get(k) and k != "updated_at"
        }
        audit.record(
            "APPLICATION_UPDATED",
            user=user,
            application=app,
            entity_type="Application",
            entity_id=app.id,
            details={"changes": changes},
        )
        return app

    def delete(self, app: Application, *, user=None) -> None:
        instances = self.instances.for_application(app.id)
        if any(i.actual_state == "RUNNING" for i in instances):
            raise ConflictError("Application has running instances. Stop them first.")
        from app.models.deployment import Deployment

        if db.session.execute(
            db.select(Deployment.id).where(Deployment.application_id == app.id).limit(1)
        ).scalar_one_or_none():
            raise ConflictError(
                "Application has deployment history and cannot be deleted. Disable it instead."
            )
        code = app.code
        db.session.delete(app)
        db.session.commit()
        audit.record(
            "APPLICATION_DELETED",
            user=user,
            entity_type="Application",
            entity_id=app.id,
            details={"code": code},
        )

    # --- compatibility -----------------------------------------------------------------------
    def check_target_compatibility(
        self, app: Application, host: TargetHost, version: ApplicationVersion | None = None
    ) -> list[str]:
        """Return a list of human readable incompatibility reasons (empty = compatible)."""
        problems: list[str] = []
        if not app.enabled:
            problems.append("Application is disabled.")
        if not host.enabled:
            problems.append(f"Host {host.name} is disabled.")
        env_code = host.environment.code
        if not app.is_environment_allowed(env_code):
            problems.append(
                f"Application is not allowed in environment {env_code} (allowed: {', '.join(app.allowed_environments)})."
            )
        if host.runtime_type == RuntimeType.NONE.value:
            problems.append(
                f"Host {host.name} has no container runtime configured. Run DISCOVER and set the runtime."
            )
        elif not app.is_runtime_allowed(host.runtime_type):
            problems.append(
                f"Application runtime {app.runtime_type} is not compatible with host runtime {host.runtime_type}."
            )
        if (
            version is not None
            and version.runtime_type != host.runtime_type
            and version.runtime_type not in (app.allowed_runtimes or [])
        ):
            problems.append(
                f"Version {version.version} was packaged for {version.runtime_type} but the host runs {host.runtime_type}."
            )
        if app.allowed_host_group_ids:
            if not app.is_host_group_allowed([g.id for g in host.groups]):
                names = [g.name for g in self.groups.all() if g.id in app.allowed_host_group_ids]
                problems.append(
                    f"Host {host.name} is not in an allowed host group ({', '.join(names)})."
                )
        if version is not None and not version.is_active:
            problems.append(f"Version {version.version} has been deactivated.")
        if (
            version is not None
            and version.package is not None
            and version.package.status != "VALID"
        ):
            problems.append(
                f"Package for version {version.version} is not valid ({version.package.status})."
            )
        return problems

    def compatible_hosts(
        self, app: Application, version: ApplicationVersion | None = None
    ) -> list[dict[str, Any]]:
        from app.repositories import HostRepository

        out = []
        for host in HostRepository().enabled():
            problems = self.check_target_compatibility(app, host, version)
            out.append(
                {
                    "host": host.to_dict(include_system=False),
                    "compatible": not problems,
                    "problems": problems,
                }
            )
        return out

    # --- versions -----------------------------------------------------------------------------------
    def deactivate_version(self, version: ApplicationVersion, *, user=None) -> ApplicationVersion:
        in_use = [
            i
            for i in self.instances.for_application(version.application_id)
            if i.current_version_id == version.id or i.desired_version_id == version.id
        ]
        if in_use:
            raise ConflictError("Version is currently deployed and cannot be deactivated.")
        version.is_active = False
        db.session.commit()
        audit.record(
            "VERSION_DEACTIVATED",
            user=user,
            application=version.application,
            entity_type="ApplicationVersion",
            entity_id=version.id,
            details={"version": version.version},
        )
        return version

    def overview(self, app: Application) -> dict[str, Any]:
        instances = self.instances.for_application(app.id)
        versions = self.versions.for_application(app.id)
        return {
            "application": app.to_dict(),
            "versions": [v.to_dict() for v in versions],
            "instances": [i.to_dict() for i in instances],
            "recent_deployments": [
                d.to_dict() for d in self.deployments.list(application_id=app.id, per_page=10).items
            ],
            "environments": [e.code for e in self.environments.all()],
            "environment_types": EnvironmentType.values(),
        }
