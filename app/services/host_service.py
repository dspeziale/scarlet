"""Target host management: CRUD, credentials, test connection, discovery."""

from __future__ import annotations

import re
from typing import Any

from flask import current_app

from app.audit import audit
from app.config.logging import get_logger
from app.deployment.remote_layout import RemoteLayout
from app.errors import ConflictError, NotFoundError, ScarletError, ValidationError
from app.extensions import db
from app.models.enums import AuditResult, CredentialType, HostStatus, RuntimeType
from app.models.host import Environment, HostGroup, RuntimeCapability, TargetCredential, TargetHost
from app.repositories import EnvironmentRepository, HostGroupRepository, HostRepository, InstanceRepository
from app.runtimes.base import HostInfo, RuntimeContext
from app.runtimes.factory import RuntimeFactory
from app.security.crypto import get_cipher
from app.security.validators import (
    validate_hostname,
    validate_ip_address,
    validate_k8s_name,
    validate_port,
    validate_ssh_username,
)
from app.ssh.command import SystemCommands, validate_remote_path
from app.ssh.factory import get_ssh_factory
from app.utils.time import utcnow

log = get_logger(__name__)
HOST_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{1,63}$")


class HostService:
    def __init__(self) -> None:
        self.hosts = HostRepository()
        self.environments = EnvironmentRepository()
        self.groups = HostGroupRepository()
        self.instances = InstanceRepository()

    # --- CRUD -------------------------------------------------------------------------------
    def _validate_payload(self, data: dict[str, Any], *, partial: bool = False) -> dict[str, Any]:
        out: dict[str, Any] = {}
        errors: dict[str, list[str]] = {}
        if "name" in data or not partial:
            name = str(data.get("name", "")).strip()
            if not HOST_NAME_RE.match(name):
                errors["name"] = ["2-64 characters: letters, digits, dot, dash, underscore."]
            out["name"] = name
        if "hostname" in data or not partial:
            try:
                out["hostname"] = validate_hostname(str(data.get("hostname", "")))
            except ValidationError as exc:
                errors.update(exc.errors)
        if "ip_address" in data:
            try:
                out["ip_address"] = validate_ip_address(data.get("ip_address"))
            except ValidationError as exc:
                errors.update(exc.errors)
        if "ssh_port" in data or not partial:
            try:
                out["ssh_port"] = validate_port(data.get("ssh_port", 22), field="ssh_port")
            except ValidationError as exc:
                errors.update(exc.errors)
        if "ssh_username" in data or not partial:
            try:
                out["ssh_username"] = validate_ssh_username(str(data.get("ssh_username", "")))
            except ValidationError as exc:
                errors.update(exc.errors)
        if "environment" in data or "environment_id" in data or not partial:
            env = None
            if data.get("environment_id"):
                env = self.environments.get(int(data["environment_id"]))
            elif data.get("environment"):
                env = self.environments.by_code(str(data["environment"]))
            if env is None:
                errors["environment"] = ["Unknown environment."]
            else:
                out["environment_id"] = env.id
        if "runtime_type" in data or not partial:
            rt = RuntimeType.parse(data.get("runtime_type", "NONE"))
            if rt is None:
                errors["runtime_type"] = [f"Must be one of {', '.join(RuntimeType.values())}."]
            else:
                out["runtime_type"] = rt.value
        if "kubernetes_namespace" in data:
            ns = data.get("kubernetes_namespace")
            try:
                out["kubernetes_namespace"] = validate_k8s_name(ns, field="kubernetes_namespace") if ns else None
            except ValidationError as exc:
                errors.update(exc.errors)
        if "kubernetes_context" in data:
            ctx = (data.get("kubernetes_context") or "").strip()
            if ctx and not re.fullmatch(r"[A-Za-z0-9@._:-]{1,128}", ctx):
                errors["kubernetes_context"] = ["Invalid context name."]
            out["kubernetes_context"] = ctx or None
        if "remote_base_path" in data:
            base = (data.get("remote_base_path") or "").strip()
            if base:
                try:
                    validate_remote_path(base, base)
                except ScarletError:
                    errors["remote_base_path"] = ["Must be an absolute, normalized path."]
            out["remote_base_path"] = base or None
        if "description" in data:
            out["description"] = str(data.get("description") or "")[:2000]
        if "enabled" in data:
            out["enabled"] = bool(data.get("enabled"))
        if "group_ids" in data and data["group_ids"] is not None:
            groups = []
            for gid in data["group_ids"]:
                group = self.groups.get(int(gid))
                if group is None:
                    errors["group_ids"] = [f"Unknown host group {gid}."]
                else:
                    groups.append(group)
            out["groups"] = groups
        if errors:
            raise ValidationError("Host data is invalid.", errors=errors)
        return out

    def create(self, data: dict[str, Any], *, user=None) -> TargetHost:
        payload = self._validate_payload(data)
        if self.hosts.by_name(payload["name"]):
            raise ConflictError(f"A host named '{payload['name']}' already exists.")
        groups = payload.pop("groups", [])
        host = TargetHost(**payload)
        host.groups = groups
        db.session.add(host)
        db.session.commit()
        audit.record("HOST_CREATED", user=user, target=host, entity_type="TargetHost", entity_id=host.id, details={"hostname": host.hostname, "environment": host.environment.code, "runtime_type": host.runtime_type})
        return host

    def update(self, host: TargetHost, data: dict[str, Any], *, user=None) -> TargetHost:
        payload = self._validate_payload(data, partial=True)
        if "name" in payload and payload["name"] != host.name and self.hosts.by_name(payload["name"]):
            raise ConflictError(f"A host named '{payload['name']}' already exists.")
        before = host.to_dict(include_system=False)
        groups = payload.pop("groups", None)
        connection_changed = any(payload.get(k) not in (None, getattr(host, k)) for k in ("hostname", "ip_address", "ssh_port"))
        for key, value in payload.items():
            setattr(host, key, value)
        if groups is not None:
            host.groups = groups
        if connection_changed and host.ssh_host_key:
            # a changed address invalidates the approved host key
            host.ssh_host_key_status = "UNKNOWN"
            host.ssh_host_key = None
            host.ssh_host_key_type = None
            host.ssh_fingerprint = None
        db.session.commit()
        after = host.to_dict(include_system=False)
        changed = {k: {"before": before.get(k), "after": after.get(k)} for k in after if before.get(k) != after.get(k) and k not in {"updated_at"}}
        audit.record("HOST_UPDATED", user=user, target=host, entity_type="TargetHost", entity_id=host.id, details={"changes": changed})
        return host

    def set_enabled(self, host: TargetHost, enabled: bool, *, user=None) -> TargetHost:
        host.enabled = enabled
        db.session.commit()
        audit.record("HOST_ENABLED" if enabled else "HOST_DISABLED", user=user, target=host, entity_type="TargetHost", entity_id=host.id)
        return host

    def delete(self, host: TargetHost, *, user=None) -> None:
        from app.models.deployment import Deployment

        instances = self.instances.for_host(host.id)
        running = [i for i in instances if i.actual_state == "RUNNING"]
        if running:
            raise ConflictError("Host still has running application instances. Stop them before deleting the host.")
        has_deployments = db.session.execute(db.select(Deployment.id).where(Deployment.target_id == host.id).limit(1)).scalar_one_or_none()
        if has_deployments:
            # keep history: disable instead of delete
            raise ConflictError("Host has deployment history and cannot be deleted. Disable it instead to preserve the audit trail.")
        name = host.name
        env = host.environment.code
        db.session.delete(host)
        db.session.commit()
        audit.record("HOST_DELETED", user=user, entity_type="TargetHost", entity_id=host.id, environment=env, details={"name": name})

    # --- credentials ---------------------------------------------------------------------------
    def set_credential(self, host: TargetHost, *, credential_type: str, secret: str, passphrase: str | None = None, username: str | None = None, user=None) -> TargetCredential:
        ctype = CredentialType.parse(credential_type)
        if ctype is None:
            raise ValidationError("Invalid credential type.", errors={"credential_type": [f"Must be one of {', '.join(CredentialType.values())}."]})
        secret = (secret or "").strip() if ctype != CredentialType.PASSWORD else (secret or "")
        if not secret:
            raise ValidationError("Secret is required.", errors={"secret": ["Required."]})
        if len(secret) > 64 * 1024:
            raise ValidationError("Secret is too large.", errors={"secret": ["Max 64 KiB."]})
        fingerprint = None
        key_type = None
        if ctype == CredentialType.PRIVATE_KEY:
            from app.ssh.client import SSHAuth
            from app.ssh.host_keys import fingerprint_of

            pkey = SSHAuth(username=host.ssh_username, private_key=secret, passphrase=passphrase or None).load_pkey()
            assert pkey is not None
            fingerprint = fingerprint_of(pkey)
            key_type = pkey.get_name()
        elif ctype == CredentialType.KUBECONFIG:
            import yaml

            try:
                parsed = yaml.safe_load(secret)
            except yaml.YAMLError as exc:
                raise ValidationError("kubeconfig is not valid YAML.", errors={"secret": ["Invalid YAML."]}) from exc
            if not isinstance(parsed, dict) or "clusters" not in parsed:
                raise ValidationError("kubeconfig does not look valid.", errors={"secret": ["Missing clusters section."]})
        if username is not None:
            username = validate_ssh_username(username)
        cipher = get_cipher()
        ssh_types = {CredentialType.PASSWORD.value, CredentialType.PRIVATE_KEY.value}
        # deactivate previous credential of the same family (rotation keeps history)
        for cred in host.credentials:
            same_family = (cred.credential_type in ssh_types) == (ctype.value in ssh_types)
            if cred.is_active and same_family:
                cred.is_active = False
                cred.rotated_at = utcnow()
        credential = TargetCredential(
            host_id=host.id,
            name="default",
            credential_type=ctype.value,
            username=username,
            encrypted_secret=cipher.encrypt(secret),
            encrypted_passphrase=cipher.encrypt(passphrase) if passphrase else None,
            key_fingerprint=fingerprint,
            key_type=key_type,
            created_by_id=getattr(user, "id", None),
            is_active=True,
        )
        db.session.add(credential)
        db.session.commit()
        audit.record("CREDENTIAL_CHANGED", user=user, target=host, entity_type="TargetCredential", entity_id=credential.id, details={"credential_type": ctype.value, "key_fingerprint": fingerprint, "key_type": key_type})
        return credential

    def revoke_credential(self, host: TargetHost, credential_id: int, *, user=None) -> None:
        cred = next((c for c in host.credentials if c.id == credential_id), None)
        if cred is None:
            raise NotFoundError("Credential not found.")
        cred.is_active = False
        cred.rotated_at = utcnow()
        db.session.commit()
        audit.record("CREDENTIAL_REVOKED", user=user, target=host, entity_type="TargetCredential", entity_id=cred.id, details={"credential_type": cred.credential_type})

    # --- remote operations (synchronous; tasks wrap these) -------------------------------------------
    def test_connection(self, host: TargetHost, *, user=None) -> dict[str, Any]:
        if not host.enabled:
            raise ValidationError("Host is disabled.")
        factory = get_ssh_factory()
        started = utcnow()
        try:
            with factory.connect(host, connect_timeout=int(current_app.config.get("SCARLET_SSH_TIMEOUT", 30))) as client:
                whoami = client.run(SystemCommands.whoami())
                hostname = client.run(SystemCommands.hostname())
            host.status = HostStatus.ONLINE.value
            host.last_seen_at = utcnow()
            host.last_error = None
            db.session.commit()
            result = {"ok": True, "remote_user": whoami.stdout.strip(), "remote_hostname": hostname.stdout.strip(), "latency_ms": int((utcnow() - started).total_seconds() * 1000), "fingerprint": host.ssh_fingerprint}
            audit.record("HOST_TEST_CONNECTION", user=user, target=host, entity_type="TargetHost", entity_id=host.id, details=result)
            return result
        except ScarletError as exc:
            host.status = HostStatus.OFFLINE.value
            host.last_error = exc.message
            db.session.commit()
            audit.record("HOST_TEST_CONNECTION", user=user, target=host, entity_type="TargetHost", entity_id=host.id, result=AuditResult.FAILURE, details={"error": exc.message, "code": exc.code})
            raise

    def discover(self, host: TargetHost, *, user=None) -> dict[str, Any]:
        """Read-only inspection of the host: OS, resources, runtimes."""
        if not host.enabled:
            raise ValidationError("Host is disabled.")
        factory = get_ssh_factory()
        data: dict[str, Any] = {"runtimes": {}}
        try:
            with factory.connect(host) as client:
                os_release = client.run(SystemCommands.os_release()).stdout
                data["os"] = _parse_os_release(os_release)
                uname = client.run(SystemCommands.uname()).stdout.split()
                data["kernel"] = uname[1] if len(uname) > 1 else None
                data["architecture"] = uname[2] if len(uname) > 2 else None
                data["cpu_count"] = _to_int(client.run(SystemCommands.nproc()).stdout)
                data["memory"] = _parse_free(client.run(SystemCommands.memory()).stdout)
                base = host.remote_base_path or current_app.config["SCARLET_REMOTE_BASE_PATH"]
                data["disk"] = _parse_df(client.run(SystemCommands.disk("/")).stdout)
                selinux = client.run(SystemCommands.selinux())
                data["selinux"] = selinux.stdout.strip() if selinux.ok else None
                data["remote_user"] = client.run(SystemCommands.whoami()).stdout.strip()
                layout = RemoteLayout(base, "discovery-probe")
                ctx = RuntimeContext(executor=client, host=HostInfo(name=host.name, runtime_type=host.runtime_type, base_path=base, kubernetes_namespace=host.kubernetes_namespace, kubernetes_context=host.kubernetes_context), application_code="discovery-probe", layout=layout, timeout=60)
                for adapter in RuntimeFactory.detectable():
                    if adapter.runtime_type == RuntimeType.KUBERNETES and host.kubernetes_credential is not None:
                        ctx.host.kubeconfig = get_cipher().decrypt(host.kubernetes_credential.encrypted_secret)
                    try:
                        detection = adapter.detect(ctx)
                    except ScarletError as exc:
                        detection = None
                        data["runtimes"][adapter.runtime_type.value] = {"available": False, "error": exc.message}
                    finally:
                        ctx.host.kubeconfig = None
                    if detection is not None:
                        data["runtimes"][adapter.runtime_type.value] = detection.to_dict()
        except ScarletError as exc:
            host.status = HostStatus.OFFLINE.value
            host.last_error = exc.message
            db.session.commit()
            audit.record("HOST_DISCOVERED", user=user, target=host, entity_type="TargetHost", entity_id=host.id, result=AuditResult.FAILURE, details={"error": exc.message})
            raise
        self._apply_discovery(host, data)
        audit.record("HOST_DISCOVERED", user=user, target=host, entity_type="TargetHost", entity_id=host.id, details={"os": data.get("os"), "runtimes": {k: v.get("available") for k, v in data["runtimes"].items()}})
        return data

    def _apply_discovery(self, host: TargetHost, data: dict[str, Any]) -> None:
        os_info = data.get("os") or {}
        host.os_name = (os_info.get("name") or "")[:64] or None
        host.os_version = (os_info.get("version_id") or os_info.get("version") or "")[:64] or None
        host.architecture = (data.get("architecture") or "")[:32] or None
        host.kernel_version = (data.get("kernel") or "")[:128] or None
        host.cpu_count = data.get("cpu_count")
        mem = data.get("memory") or {}
        host.memory_total_mb = mem.get("total_mb")
        host.memory_available_mb = mem.get("available_mb")
        disk = data.get("disk") or {}
        host.disk_total_mb = disk.get("total_mb")
        host.disk_available_mb = disk.get("available_mb")
        host.status = HostStatus.ONLINE.value
        host.last_seen_at = utcnow()
        host.last_discovery_at = utcnow()
        host.last_error = None
        host.discovery_data = data
        existing = {c.runtime_type: c for c in host.capabilities}
        for runtime, info in data.get("runtimes", {}).items():
            cap = existing.get(runtime)
            if cap is None:
                cap = RuntimeCapability(host_id=host.id, runtime_type=runtime)
                db.session.add(cap)
            cap.available = bool(info.get("available"))
            cap.version = (info.get("version") or None)
            cap.rootless = info.get("rootless")
            cap.binary_path = info.get("binary_path")
            cap.details = info.get("details") or {}
            cap.detected_at = utcnow()
        configured = data.get("runtimes", {}).get(host.runtime_type)
        if configured and configured.get("available"):
            host.runtime_version = configured.get("version")
            host.runtime_rootless = configured.get("rootless")
            if host.runtime_type == RuntimeType.KUBERNETES.value:
                host.kubernetes_version = configured.get("version")
        elif host.runtime_type == RuntimeType.NONE.value:
            # suggest the first available runtime without changing configuration
            available = [k for k, v in data.get("runtimes", {}).items() if v.get("available")]
            data["suggested_runtime"] = available[0] if available else None
        db.session.commit()

    def refresh_status(self, host: TargetHost) -> dict[str, Any]:
        return self.test_connection(host)

    # --- host groups -------------------------------------------------------------------------------------
    def create_group(self, *, name: str, description: str = "", environment_id: int | None = None, host_ids: list[int] | None = None, user=None) -> HostGroup:
        name = (name or "").strip()
        if not HOST_NAME_RE.match(name):
            raise ValidationError("Invalid group name.", errors={"name": ["2-64 characters."]})
        if self.groups.by_name(name):
            raise ConflictError("Host group already exists.")
        group = HostGroup(name=name, description=(description or "")[:255], environment_id=environment_id)
        group.hosts = self._resolve_hosts(host_ids or [], environment_id)
        db.session.add(group)
        db.session.commit()
        audit.record("HOST_GROUP_CREATED", user=user, entity_type="HostGroup", entity_id=group.id, details={"name": name, "hosts": [h.name for h in group.hosts]})
        return group

    def update_group(self, group: HostGroup, *, description: str | None = None, environment_id: int | None = None, host_ids: list[int] | None = None, user=None) -> HostGroup:
        if description is not None:
            group.description = description[:255]
        if environment_id is not None:
            group.environment_id = environment_id or None
        if host_ids is not None:
            group.hosts = self._resolve_hosts(host_ids, group.environment_id)
        db.session.commit()
        audit.record("HOST_GROUP_UPDATED", user=user, entity_type="HostGroup", entity_id=group.id, details={"name": group.name, "hosts": [h.name for h in group.hosts]})
        return group

    def delete_group(self, group: HostGroup, *, user=None) -> None:
        db.session.delete(group)
        db.session.commit()
        audit.record("HOST_GROUP_DELETED", user=user, entity_type="HostGroup", entity_id=group.id, details={"name": group.name})

    def _resolve_hosts(self, host_ids: list[int], environment_id: int | None) -> list[TargetHost]:
        hosts = []
        for hid in host_ids:
            host = self.hosts.get(int(hid))
            if host is None:
                raise ValidationError(f"Unknown host {hid}.", errors={"host_ids": [f"Unknown host {hid}"]})
            if environment_id and host.environment_id != environment_id:
                raise ValidationError(f"Host {host.name} is not in the group's environment.", errors={"host_ids": ["Environment mismatch."]})
            hosts.append(host)
        return hosts

    # --- environments ---------------------------------------------------------------------------------------
    def update_environment(self, env: Environment, data: dict[str, Any], *, user=None) -> Environment:
        for key in ("name", "description", "color"):
            if key in data and data[key] is not None:
                setattr(env, key, str(data[key])[:255])
        for key in ("require_confirmation", "require_approval", "allow_rollback"):
            if key in data and data[key] is not None:
                setattr(env, key, bool(data[key]))
        if "max_parallel_deployments" in data and data["max_parallel_deployments"] is not None:
            value = int(data["max_parallel_deployments"])
            if not 1 <= value <= 50:
                raise ValidationError("max_parallel_deployments out of range.", errors={"max_parallel_deployments": ["1-50"]})
            env.max_parallel_deployments = value
        db.session.commit()
        audit.record("ENVIRONMENT_UPDATED", user=user, entity_type="Environment", entity_id=env.id, environment=env.code, details=env.to_dict())
        return env


# --- parsers --------------------------------------------------------------------------------------------------


def _parse_os_release(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        out[key.strip().lower()] = value.strip().strip('"')
    return {"name": out.get("name"), "version": out.get("version"), "version_id": out.get("version_id"), "id": out.get("id"), "pretty_name": out.get("pretty_name")}


def _to_int(text: str) -> int | None:
    try:
        return int(text.strip().split()[0])
    except (ValueError, IndexError):
        return None


def _parse_free(text: str) -> dict[str, int | None]:
    for line in text.splitlines():
        if line.lower().startswith("mem:"):
            parts = line.split()
            try:
                return {"total_mb": int(parts[1]), "used_mb": int(parts[2]), "available_mb": int(parts[-1])}
            except (ValueError, IndexError):
                break
    return {"total_mb": None, "used_mb": None, "available_mb": None}


def _parse_df(text: str) -> dict[str, Any]:
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) < 2:
        return {"total_mb": None, "used_mb": None, "available_mb": None}
    parts = lines[-1].split()
    try:
        return {"filesystem": parts[0], "total_mb": int(parts[1]), "used_mb": int(parts[2]), "available_mb": int(parts[3]), "use_percent": int(parts[4].rstrip("%")), "mount": parts[5] if len(parts) > 5 else None}
    except (ValueError, IndexError):
        return {"total_mb": None, "used_mb": None, "available_mb": None}
