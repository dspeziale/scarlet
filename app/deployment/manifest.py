"""SCARLET release manifest schema (``manifest.yaml``), version 1.

The manifest is the contract between application teams and operations. It is
validated with Pydantic and every field that may end up in a remote command is
additionally checked against the strict allowlist validators.

See ``docs/APPLICATION_RELEASE_CONTRACT.md`` for the human readable contract.
"""

from __future__ import annotations

import shlex
from typing import Any, Literal

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)
from pydantic import (
    ValidationError as PydanticValidationError,
)

from app.errors import ManifestValidationError
from app.security.validators import (
    parse_semver,
    validate_app_code,
    validate_env_key,
    validate_image_name,
    validate_image_tag,
    validate_k8s_name,
    validate_relative_path,
    validate_url_path,
)

SUPPORTED_MANIFEST_VERSIONS = {1}
RUNTIMES = ("docker", "podman", "kubernetes")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ImageSpec(_Strict):
    name: str
    tag: str
    archive: str | None = Field(
        default=None, description="Path inside the package to an image archive (`docker save`)"
    )
    pull_policy: Literal["if-not-present", "always", "never"] = "if-not-present"

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        return validate_image_name(v)

    @field_validator("tag")
    @classmethod
    def _tag(cls, v: str) -> str:
        return validate_image_tag(v)

    @field_validator("archive")
    @classmethod
    def _archive(cls, v: str | None) -> str | None:
        return validate_relative_path(v, field="image.archive") if v else None

    @property
    def reference(self) -> str:
        return f"{self.name}:{self.tag}"


class PortSpec(_Strict):
    container: int = Field(ge=1, le=65535)
    host: int | None = Field(default=None, ge=1, le=65535)
    protocol: Literal["tcp", "udp"] = "tcp"
    bind: str | None = Field(
        default=None, description="Host interface to bind (IPv4 only), e.g. 127.0.0.1"
    )

    @field_validator("bind")
    @classmethod
    def _bind(cls, v: str | None) -> str | None:
        if v is None:
            return None
        import ipaddress

        return str(ipaddress.IPv4Address(v))

    def as_publish_arg(self) -> str:
        host = self.host or self.container
        prefix = f"{self.bind}:" if self.bind else ""
        suffix = "" if self.protocol == "tcp" else "/udp"
        return f"{prefix}{host}:{self.container}{suffix}"


class VolumeSpec(_Strict):
    name: str
    mount: str
    shared: Literal["data", "config", "logs"] = "data"
    read_only: bool = False

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        return validate_relative_path(v, field="volumes.name", max_depth=1)

    @field_validator("mount")
    @classmethod
    def _mount(cls, v: str) -> str:
        if not v.startswith("/") or ".." in v or ":" in v or "," in v or "\x00" in v:
            raise ValueError("mount must be an absolute container path without ':' or '..'")
        return v


class HealthcheckSpec(_Strict):
    type: Literal["http", "https", "tcp", "command", "container_status", "kubernetes_status"] = (
        "container_status"
    )
    path: str = "/health"
    port: int | None = Field(default=None, ge=1, le=65535)
    expected_status: int = Field(default=200, ge=100, le=599)
    timeout: int = Field(default=10, ge=1, le=300)
    retries: int = Field(default=5, ge=1, le=50)
    interval: int = Field(default=3, ge=0, le=300)
    command: str | None = Field(
        default=None, description="Command executed inside the container (exec)"
    )

    @field_validator("path")
    @classmethod
    def _path(cls, v: str) -> str:
        return validate_url_path(v)

    @field_validator("command")
    @classmethod
    def _command(cls, v: str | None) -> str | None:
        if v is None:
            return None
        parts = shlex.split(v)
        if not parts or len(parts) > 32:
            raise ValueError("command must contain between 1 and 32 arguments")
        for part in parts:
            if any(ch in part for ch in "\n\r\x00;|&$`"):
                raise ValueError("command contains forbidden shell characters")
        return v

    @model_validator(mode="after")
    def _consistency(self) -> HealthcheckSpec:
        if self.type == "command" and not self.command:
            raise ValueError("healthcheck.command is required when type is 'command'")
        return self

    def command_argv(self) -> tuple[str, ...]:
        return tuple(shlex.split(self.command)) if self.command else ()


class DeploymentSpec(_Strict):
    strategy: Literal["recreate", "rolling"] = "recreate"
    start_timeout: int = Field(default=120, ge=5, le=3600)
    stop_timeout: int = Field(default=60, ge=1, le=3600)
    stop_grace_period: int = Field(default=10, ge=0, le=600)
    restart_policy: Literal["always", "unless-stopped", "on-failure", "no"] = "unless-stopped"
    replicas: int = Field(default=1, ge=0, le=100)
    user: str | None = Field(default=None, description="Container user (uid[:gid])")
    read_only_rootfs: bool = False
    extra_args_allowed: bool = (
        False  # reserved; extra runtime args are never accepted from the manifest
    )

    @field_validator("user")
    @classmethod
    def _user(cls, v: str | None) -> str | None:
        import re

        if v is not None and not re.fullmatch(r"\d{1,6}(:\d{1,6})?", v):
            raise ValueError("user must be numeric uid or uid:gid")
        return v


class ResourcesSpec(_Strict):
    cpu: str | None = None
    memory: str | None = None

    @field_validator("cpu")
    @classmethod
    def _cpu(cls, v: str | None) -> str | None:
        import re

        if v is not None and not re.fullmatch(r"\d+(\.\d+)?m?", v):
            raise ValueError("cpu must look like '1', '0.5' or '500m'")
        return v

    @field_validator("memory")
    @classmethod
    def _memory(cls, v: str | None) -> str | None:
        import re

        if v is not None and not re.fullmatch(r"\d+(Ki|Mi|Gi|K|M|G|k|m|g)?", v):
            raise ValueError("memory must look like '512Mi' or '1Gi'")
        return v

    def memory_for_cli(self) -> str | None:
        if not self.memory:
            return None
        return self.memory.replace("Ki", "k").replace("Mi", "m").replace("Gi", "g")

    def cpu_for_cli(self) -> str | None:
        if not self.cpu:
            return None
        if self.cpu.endswith("m"):
            return str(int(self.cpu[:-1]) / 1000)
        return self.cpu


class HooksSpec(_Strict):
    pre_deploy: list[str] = Field(default_factory=list)
    migrate: list[str] = Field(default_factory=list)
    post_deploy: list[str] = Field(default_factory=list)
    pre_rollback: list[str] = Field(default_factory=list)
    post_rollback: list[str] = Field(default_factory=list)
    timeout: int = Field(default=300, ge=1, le=3600)

    @field_validator("pre_deploy", "migrate", "post_deploy", "pre_rollback", "post_rollback")
    @classmethod
    def _scripts(cls, values: list[str]) -> list[str]:
        out = []
        for v in values:
            path = validate_relative_path(v, field="hooks")
            if not path.startswith("scripts/") or not path.endswith(".sh"):
                raise ValueError(f"hook '{v}' must be a .sh file under scripts/")
            out.append(path)
        return out

    def all_scripts(self) -> list[str]:
        return (
            self.pre_deploy
            + self.migrate
            + self.post_deploy
            + self.pre_rollback
            + self.post_rollback
        )


class DependencySpec(_Strict):
    name: str
    type: Literal["service", "database", "queue", "application", "other"] = "service"
    required: bool = True
    description: str = ""


class HelmSpec(_Strict):
    chart: str
    values: list[str] = Field(default_factory=list)
    release_name: str | None = None

    @field_validator("chart")
    @classmethod
    def _chart(cls, v: str) -> str:
        return validate_relative_path(v, field="kubernetes.helm.chart")

    @field_validator("values")
    @classmethod
    def _values(cls, v: list[str]) -> list[str]:
        return [validate_relative_path(x, field="kubernetes.helm.values") for x in v]


class KubernetesServiceSpec(_Strict):
    type: Literal["ClusterIP", "NodePort", "LoadBalancer"] = "ClusterIP"
    port: int = Field(default=80, ge=1, le=65535)
    target_port: int | None = Field(default=None, ge=1, le=65535)


class KubernetesSpec(_Strict):
    namespace: str | None = None
    manifests: str | None = Field(
        default="kubernetes", description="Directory with YAML manifests inside the package"
    )
    helm: HelmSpec | None = None
    deployment_name: str | None = None
    container_name: str | None = None
    service: KubernetesServiceSpec | None = None

    @field_validator("namespace", "deployment_name", "container_name")
    @classmethod
    def _names(cls, v: str | None) -> str | None:
        return validate_k8s_name(v) if v else None

    @field_validator("manifests")
    @classmethod
    def _manifests(cls, v: str | None) -> str | None:
        return validate_relative_path(v, field="kubernetes.manifests") if v else None


class ComposeSpec(_Strict):
    file: str = "docker-compose.yml"
    project_name: str | None = None

    @field_validator("file")
    @classmethod
    def _file(cls, v: str) -> str:
        path = validate_relative_path(v, field="compose.file")
        if not path.endswith((".yml", ".yaml")):
            raise ValueError("compose.file must be a YAML file")
        return path


class RollbackSpec(_Strict):
    enabled: bool = True
    keep_releases: int = Field(default=5, ge=2, le=50)


class Manifest(_Strict):
    manifest_version: int
    application: str
    version: str
    runtime: Literal["docker", "podman", "kubernetes"]
    description: str = ""
    image: ImageSpec | None = None
    ports: list[PortSpec] = Field(default_factory=list)
    environment: dict[str, str] = Field(default_factory=dict)
    environment_files: list[str] = Field(default_factory=list)
    secrets: list[str] = Field(default_factory=list)
    volumes: list[VolumeSpec] = Field(default_factory=list)
    healthcheck: HealthcheckSpec = Field(default_factory=HealthcheckSpec)
    deployment: DeploymentSpec = Field(default_factory=DeploymentSpec)
    resources: ResourcesSpec = Field(default_factory=ResourcesSpec)
    hooks: HooksSpec = Field(default_factory=HooksSpec)
    dependencies: list[DependencySpec] = Field(default_factory=list)
    kubernetes: KubernetesSpec | None = None
    compose: ComposeSpec | None = None
    rollback: RollbackSpec = Field(default_factory=RollbackSpec)
    metadata: dict[str, str] = Field(default_factory=dict)

    @field_validator("manifest_version")
    @classmethod
    def _mv(cls, v: int) -> int:
        if v not in SUPPORTED_MANIFEST_VERSIONS:
            raise ValueError(
                f"unsupported manifest_version {v}; supported: {sorted(SUPPORTED_MANIFEST_VERSIONS)}"
            )
        return v

    @field_validator("application")
    @classmethod
    def _app(cls, v: str) -> str:
        return validate_app_code(v)

    @field_validator("version")
    @classmethod
    def _version(cls, v: str) -> str:
        return parse_semver(v)["version"]

    @field_validator("environment")
    @classmethod
    def _env(cls, v: dict[str, str]) -> dict[str, str]:
        out: dict[str, str] = {}
        for key, value in v.items():
            validate_env_key(key)
            if key.startswith("SCARLET_"):
                raise ValueError(f"environment key {key} is reserved")
            value = str(value)
            if "\n" in value or "\x00" in value:
                raise ValueError(f"environment value for {key} contains forbidden characters")
            out[key] = value
        return out

    @field_validator("environment_files")
    @classmethod
    def _env_files(cls, v: list[str]) -> list[str]:
        return [validate_relative_path(x, field="environment_files") for x in v]

    @field_validator("secrets")
    @classmethod
    def _secrets(cls, v: list[str]) -> list[str]:
        return [validate_env_key(x) for x in v]

    @field_validator("metadata")
    @classmethod
    def _metadata(cls, v: dict[str, str]) -> dict[str, str]:
        if len(v) > 32:
            raise ValueError("at most 32 metadata entries are allowed")
        return {str(k)[:64]: str(val)[:256] for k, val in v.items()}

    @model_validator(mode="after")
    def _cross(self) -> Manifest:
        if self.runtime in {"docker", "podman"}:
            if self.image is None and self.compose is None:
                raise ValueError("image or compose is required for docker/podman runtimes")
            if self.image is not None and self.compose is not None:
                raise ValueError("specify either image or compose, not both")
            if (
                self.image is not None
                and self.image.pull_policy == "never"
                and not self.image.archive
            ):
                raise ValueError("image.pull_policy 'never' requires image.archive")
        if self.runtime == "kubernetes":
            if self.kubernetes is None:
                raise ValueError("kubernetes section is required for the kubernetes runtime")
            if not self.kubernetes.manifests and not self.kubernetes.helm:
                raise ValueError("kubernetes.manifests or kubernetes.helm is required")
            if self.compose is not None:
                raise ValueError("compose is not valid for the kubernetes runtime")
        if self.healthcheck.type in {"http", "https", "tcp"} and self.healthcheck.port is None:
            if self.ports:
                object.__setattr__(
                    self.healthcheck, "port", self.ports[0].host or self.ports[0].container
                )
            elif self.kubernetes and self.kubernetes.service:
                object.__setattr__(self.healthcheck, "port", self.kubernetes.service.port)
            else:
                raise ValueError(
                    "healthcheck.port is required for http/https/tcp checks without ports"
                )
        if self.healthcheck.type == "kubernetes_status" and self.runtime != "kubernetes":
            raise ValueError("kubernetes_status health check requires the kubernetes runtime")
        if self.healthcheck.type == "container_status" and self.runtime == "kubernetes":
            object.__setattr__(self.healthcheck, "type", "kubernetes_status")
        host_ports = [p.host or p.container for p in self.ports]
        if len(host_ports) != len(set(host_ports)):
            raise ValueError("duplicate host ports in ports")
        return self

    # --- helpers --------------------------------------------------------------------
    @property
    def runtime_type(self) -> str:
        return self.runtime.upper()

    def required_files(self) -> list[str]:
        files: list[str] = []
        if self.image and self.image.archive:
            files.append(self.image.archive)
        files.extend(self.environment_files)
        files.extend(self.hooks.all_scripts())
        if self.compose:
            files.append(self.compose.file)
        if self.kubernetes and self.kubernetes.helm:
            files.extend(self.kubernetes.helm.values)
        return files

    def required_dirs(self) -> list[str]:
        dirs: list[str] = []
        if self.kubernetes and self.kubernetes.manifests:
            dirs.append(self.kubernetes.manifests)
        if self.kubernetes and self.kubernetes.helm:
            dirs.append(self.kubernetes.helm.chart)
        return dirs

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)


def _format_pydantic_errors(exc: PydanticValidationError) -> list[str]:
    messages = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err.get("loc", ())) or "manifest"
        msg = err.get("msg", "invalid value")
        messages.append(f"{loc}: {msg}")
    return messages


def parse_manifest(text: str | bytes) -> Manifest:
    """Parse and validate manifest YAML. Raises ``ManifestValidationError``."""
    if isinstance(text, bytes):
        if len(text) > 256 * 1024:
            raise ManifestValidationError("manifest.yaml is too large (max 256 KiB).")
        text = text.decode("utf-8", "strict") if _is_utf8(text) else ""
        if not text:
            raise ManifestValidationError("manifest.yaml must be UTF-8 encoded text.")
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ManifestValidationError(f"manifest.yaml is not valid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise ManifestValidationError("manifest.yaml must contain a mapping at the top level.")
    try:
        return Manifest.model_validate(data)
    except PydanticValidationError as exc:
        errors = _format_pydantic_errors(exc)
        raise ManifestValidationError(
            "manifest.yaml failed validation: " + "; ".join(errors), errors={"manifest": errors}
        ) from exc


def _is_utf8(data: bytes) -> bool:
    try:
        data.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False


def dump_manifest(manifest: Manifest) -> str:
    return yaml.safe_dump(manifest.to_dict(), sort_keys=False)
