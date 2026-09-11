"""Pre-flight checks executed before a deployment is queued and again by the worker."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from flask import current_app

from app.config.logging import get_logger
from app.deployment.remote_layout import RemoteLayout
from app.deployment.storage import get_artifact_storage
from app.errors import ScarletError
from app.lifecycle.locks import get_lock_manager, runtime_lock_key
from app.models.application import Application, ApplicationVersion
from app.models.enums import HostKeyStatus, RuntimeType
from app.models.host import TargetHost
from app.repositories import DeploymentRepository, InstanceRepository
from app.runtimes.base import HostInfo, RuntimeContext
from app.runtimes.factory import RuntimeFactory
from app.security.crypto import get_cipher
from app.services.application_service import ApplicationService
from app.services.configuration_service import ConfigurationService
from app.services.host_service import _parse_df, _parse_free
from app.ssh.command import FileCommands, SystemCommands
from app.ssh.factory import get_ssh_factory

log = get_logger(__name__)

MIN_FREE_DISK_MB = 512
MIN_FREE_MEMORY_MB = 128


@dataclass
class Check:
    name: str
    label: str
    status: str  # PASS | WARN | FAIL | SKIP
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "status": self.status,
            "message": self.message,
            "details": self.details,
        }


@dataclass
class PreflightResult:
    checks: list[Check]

    @property
    def ok(self) -> bool:
        return not any(c.status == "FAIL" for c in self.checks)

    @property
    def warnings(self) -> list[Check]:
        return [c for c in self.checks if c.status == "WARN"]

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "checks": [c.to_dict() for c in self.checks],
            "failed": [c.name for c in self.checks if c.status == "FAIL"],
            "warnings": [c.name for c in self.warnings],
        }


class PreflightService:
    def __init__(self) -> None:
        self.apps = ApplicationService()
        self.config = ConfigurationService()
        self.instances = InstanceRepository()
        self.deployments = DeploymentRepository()

    def run(
        self,
        application: Application,
        version: ApplicationVersion,
        host: TargetHost,
        *,
        remote: bool = True,
    ) -> PreflightResult:
        checks: list[Check] = []
        manifest = version.manifest or {}

        # --- static checks (no SSH) ---------------------------------------------------------
        problems = self.apps.check_target_compatibility(application, host, version)
        checks.append(
            Check(
                "compatibility",
                "Application / target compatibility",
                "FAIL" if problems else "PASS",
                (
                    "; ".join(problems)
                    if problems
                    else "Runtime, environment and host group rules satisfied"
                ),
                {"problems": problems},
            )
        )
        checks.append(
            Check(
                "target_enabled",
                "Target enabled",
                "PASS" if host.enabled else "FAIL",
                "" if host.enabled else "Host is disabled",
            )
        )
        checks.append(
            Check(
                "environment",
                "Environment",
                "PASS",
                f"{host.environment.code}{' (PRODUCTION)' if host.is_production else ''}",
                {"is_production": host.is_production},
            )
        )

        if (
            host.ssh_host_key_status != HostKeyStatus.APPROVED.value
            and current_app.config.get("SCARLET_SSH_HOST_KEY_POLICY") == "strict"
        ):
            checks.append(
                Check(
                    "host_key",
                    "SSH host key approved",
                    "FAIL",
                    f"Host key status is {host.ssh_host_key_status}. Approve the fingerprint first.",
                )
            )
        else:
            checks.append(
                Check(
                    "host_key",
                    "SSH host key approved",
                    "PASS",
                    host.ssh_fingerprint or "trust-on-first-use",
                )
            )
        checks.append(
            Check(
                "credential",
                "SSH credential configured",
                "PASS" if host.active_credential else "FAIL",
                (
                    host.active_credential.credential_type
                    if host.active_credential
                    else "No active SSH credential"
                ),
            )
        )

        # package integrity
        try:
            storage = get_artifact_storage()
            if version.package is None or not storage.exists(version.package.storage_key):
                checks.append(
                    Check("package", "Package integrity", "FAIL", "Artifact not found in storage")
                )
            else:
                actual = storage.checksum(version.package.storage_key)
                ok = actual == version.checksum_sha256
                checks.append(
                    Check(
                        "package",
                        "Package integrity",
                        "PASS" if ok else "FAIL",
                        "SHA-256 verified" if ok else "Artifact checksum mismatch",
                        {"checksum": actual},
                    )
                )
        except ScarletError as exc:
            checks.append(Check("package", "Package integrity", "FAIL", exc.message))

        # configuration & secrets
        try:
            _, missing = self.config.render_environment(application, host.environment, manifest)
            checks.append(
                Check(
                    "secrets",
                    "Required secrets configured",
                    "FAIL" if missing else "PASS",
                    (
                        f"Missing: {', '.join(missing)}"
                        if missing
                        else "All manifest secrets are configured"
                    ),
                    {"missing": missing},
                )
            )
        except ScarletError as exc:
            checks.append(Check("secrets", "Required secrets configured", "FAIL", exc.message))

        # conflicting operations
        lock_key = runtime_lock_key(host.id, application.id)
        try:
            locked = get_lock_manager().is_locked(lock_key)
        except Exception:  # noqa: BLE001
            locked = False
        active = self.deployments.active_for(application.id, host.id)
        if locked or active:
            checks.append(
                Check(
                    "conflicts",
                    "No conflicting operation",
                    "FAIL",
                    "Another deployment/operation is in progress for this application on this host",
                    {"active_deployments": [d.reference for d in active]},
                )
            )
        else:
            checks.append(Check("conflicts", "No conflicting operation", "PASS"))

        # existing deployment state
        instance = self.instances.get_for(application.id, host.id)
        if (
            instance is not None
            and instance.current_version_id == version.id
            and instance.actual_state == "RUNNING"
        ):
            checks.append(
                Check(
                    "existing_state",
                    "Existing deployment state",
                    "WARN",
                    f"Version {version.version} is already running on this host; the deployment will recreate it",
                    {"current_version": version.version},
                )
            )
        else:
            current = (
                instance.current_version.version if instance and instance.current_version else None
            )
            checks.append(
                Check(
                    "existing_state",
                    "Existing deployment state",
                    "PASS",
                    f"Current version: {current or 'none'}",
                    {
                        "current_version": current,
                        "state": instance.actual_state if instance else "NOT_INSTALLED",
                    },
                )
            )

        # parallel deployment limit
        limit = (
            host.environment.max_parallel_deployments
            if host.environment.max_parallel_deployments
            else int(current_app.config.get("SCARLET_MAX_PARALLEL_DEPLOYMENTS", 3))
        )
        if host.is_production:
            limit = min(
                limit, int(current_app.config.get("SCARLET_PROD_MAX_PARALLEL_DEPLOYMENTS", 1))
            )
        running = self.deployments.running_count(host.environment_id)
        checks.append(
            Check(
                "parallel_limit",
                "Parallel deployment limit",
                "FAIL" if running >= limit else "PASS",
                f"{running}/{limit} deployments running in {host.environment.code}",
                {"running": running, "limit": limit},
            )
        )

        if not remote or any(
            c.status == "FAIL" and c.name in {"credential", "host_key", "target_enabled"}
            for c in checks
        ):
            if remote:
                checks.append(
                    Check("ssh", "SSH connectivity", "SKIP", "Skipped because prerequisites failed")
                )
            return PreflightResult(checks)

        # --- remote checks -----------------------------------------------------------------------
        checks.extend(self._remote_checks(application, version, host, manifest))
        return PreflightResult(checks)

    def _remote_checks(
        self,
        application: Application,
        version: ApplicationVersion,
        host: TargetHost,
        manifest: dict[str, Any],
    ) -> list[Check]:
        checks: list[Check] = []
        base = host.remote_base_path or current_app.config["SCARLET_REMOTE_BASE_PATH"]
        try:
            factory = get_ssh_factory()
            with factory.connect(host) as client:
                checks.append(
                    Check("ssh", "SSH connectivity", "PASS", f"Connected as {host.ssh_username}")
                )
                # runtime
                adapter = RuntimeFactory.get(host.runtime_type)
                layout = RemoteLayout(base, application.code)
                info = HostInfo(
                    name=host.name,
                    runtime_type=host.runtime_type,
                    base_path=base,
                    kubernetes_namespace=host.kubernetes_namespace,
                    kubernetes_context=host.kubernetes_context,
                )
                if (
                    host.runtime_type == RuntimeType.KUBERNETES.value
                    and host.kubernetes_credential is not None
                ):
                    info.kubeconfig = get_cipher().decrypt(
                        host.kubernetes_credential.encrypted_secret
                    )
                ctx = RuntimeContext(
                    executor=client,
                    host=info,
                    application_code=application.code,
                    layout=layout,
                    timeout=60,
                )
                detection = adapter.detect(ctx)
                checks.append(
                    Check(
                        "runtime",
                        f"{host.runtime_type} runtime available",
                        "PASS" if detection.available else "FAIL",
                        (
                            f"version {detection.version}"
                            if detection.available
                            else detection.details.get("reason", "runtime not available")
                        ),
                        detection.to_dict(),
                    )
                )
                if host.runtime_type == RuntimeType.PODMAN.value and detection.rootless is not None:
                    checks.append(
                        Check(
                            "rootless",
                            "Podman mode",
                            "PASS",
                            "rootless" if detection.rootless else "rootful",
                        )
                    )
                # disk
                df = _parse_df(client.run(SystemCommands.disk("/")).stdout)
                needed_mb = max(
                    MIN_FREE_DISK_MB,
                    int(
                        ((version.package.size_bytes if version.package else 0) * 3) / (1024 * 1024)
                    )
                    + 100,
                )
                avail = df.get("available_mb")
                if avail is None:
                    checks.append(
                        Check(
                            "disk",
                            "Sufficient disk space",
                            "WARN",
                            "Could not determine free disk space",
                        )
                    )
                else:
                    checks.append(
                        Check(
                            "disk",
                            "Sufficient disk space",
                            "PASS" if avail >= needed_mb else "FAIL",
                            f"{avail} MB free, {needed_mb} MB required",
                            {"available_mb": avail, "required_mb": needed_mb},
                        )
                    )
                # memory
                mem = _parse_free(client.run(SystemCommands.memory()).stdout)
                required_mem = _memory_mb(manifest) or MIN_FREE_MEMORY_MB
                if mem.get("available_mb") is None:
                    checks.append(
                        Check(
                            "memory",
                            "Sufficient memory",
                            "WARN",
                            "Could not determine available memory",
                        )
                    )
                else:
                    ok = mem["available_mb"] >= required_mem
                    checks.append(
                        Check(
                            "memory",
                            "Sufficient memory",
                            "PASS" if ok else "WARN",
                            f"{mem['available_mb']} MB available, {required_mem} MB requested",
                            {"available_mb": mem["available_mb"], "required_mb": required_mem},
                        )
                    )
                # base path writable
                fs = FileCommands(base)
                probe_dir = layout.staging_dir
                try:
                    client.run(fs.mkdir(probe_dir))
                    checks.append(Check("base_path", "Remote base path writable", "PASS", base))
                except ScarletError as exc:
                    checks.append(
                        Check(
                            "base_path",
                            "Remote base path writable",
                            "FAIL",
                            f"Cannot create {probe_dir}: {exc.message}",
                        )
                    )
                # ports (container runtimes)
                if host.runtime_type in {RuntimeType.DOCKER.value, RuntimeType.PODMAN.value}:
                    checks.append(self._port_check(client, ctx, adapter, manifest, application))
                # release already present?
                exists = client.run(fs.is_dir(layout.release_dir(version.version)))
                if exists.ok:
                    checks.append(
                        Check(
                            "release_dir",
                            "Release directory",
                            "WARN",
                            f"Release {version.version} already exists on the host and will be reused/replaced",
                        )
                    )
                else:
                    checks.append(
                        Check("release_dir", "Release directory", "PASS", "New release directory")
                    )
        except ScarletError as exc:
            checks.append(Check("ssh", "SSH connectivity", "FAIL", exc.message, {"code": exc.code}))
        return checks

    def _port_check(self, client, ctx, adapter, manifest, application) -> Check:
        ports = manifest.get("ports") or []
        if not ports:
            return Check("ports", "Required ports", "SKIP", "No published ports")
        try:
            actual = adapter.status(ctx)
        except ScarletError:
            actual = None
        if actual is not None and actual.state.value == "RUNNING":
            return Check(
                "ports",
                "Required ports",
                "PASS",
                "Ports are used by the current release of this application (will be recreated)",
            )
        busy = []
        for port in ports:
            host_port = port.get("host") or port.get("container")
            from app.ssh.command import RemoteCommand

            probe = client.run(
                RemoteCommand(
                    ("nc", "-z", "-w", "1", "127.0.0.1", str(int(host_port))),
                    "health.tcp",
                    "Port probe",
                    allow_failure=True,
                    timeout=5,
                )
            )
            if probe.ok:
                busy.append(int(host_port))
        if busy:
            return Check(
                "ports",
                "Required ports",
                "FAIL",
                f"Ports already in use on the host: {busy}",
                {"busy": busy},
            )
        return Check(
            "ports",
            "Required ports",
            "PASS",
            f"Ports free: {[p.get('host') or p.get('container') for p in ports]}",
        )


def _memory_mb(manifest: dict[str, Any]) -> int | None:
    mem = (manifest.get("resources") or {}).get("memory")
    if not mem:
        return None
    units = {
        "Ki": 1 / 1024,
        "Mi": 1,
        "Gi": 1024,
        "K": 1 / 1024,
        "M": 1,
        "G": 1024,
        "k": 1 / 1024,
        "m": 1,
        "g": 1024,
    }
    for suffix, factor in units.items():
        if mem.endswith(suffix):
            try:
                return int(float(mem[: -len(suffix)]) * factor)
            except ValueError:
                return None
    try:
        return int(int(mem) / (1024 * 1024))
    except ValueError:
        return None
