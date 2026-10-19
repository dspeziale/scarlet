"""Bootstrap configuration.

Sources, from lowest to highest priority:
  1. defaults defined here
  2. YAML file (PKM_CONFIG, default /etc/pkm/config.yaml when present)
  3. environment variables  PKM_<SECTION>__<KEY>  (e.g. PKM_SERVER__PORT=8443)

Runtime settings changed from the UI are stored in the database and layered on
top by :mod:`pkm.runtime_settings`; only a whitelisted subset can be changed there.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

DEFAULT_CONFIG_PATH = "/etc/pkm/config.yaml"


class ServerConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = Field(8080, ge=1, le=65535)
    tls_cert: str | None = None
    tls_key: str | None = None
    # Reverse proxies whose X-Forwarded-* headers are trusted (IP addresses).
    trusted_proxies: list[str] = Field(default_factory=list)
    static_dir: str | None = None
    graceful_shutdown_seconds: int = Field(20, ge=1, le=300)

    @property
    def tls_enabled(self) -> bool:
        return bool(self.tls_cert and self.tls_key)


class KubernetesConfig(BaseModel):
    enabled: bool = True
    kubeconfig: str | None = None
    context: str | None = None
    in_cluster: bool = False
    connect_timeout: float = Field(5, gt=0, le=60)
    request_timeout: float = Field(20, gt=0, le=300)
    cache_ttl_seconds: float = Field(3, ge=0, le=60)


class PodmanConfig(BaseModel):
    enabled: bool = True
    # unix:///run/podman/podman.sock  or  http://host:port  (only for trusted networks)
    url: str = "unix:///run/podman/podman.sock"
    timeout: float = Field(10, gt=0, le=300)


class DatabaseConfig(BaseModel):
    path: str = "/var/lib/pkm/pkm.db"


class AuthConfig(BaseModel):
    session_idle_minutes: int = Field(30, ge=5, le=24 * 60)
    session_absolute_hours: int = Field(12, ge=1, le=24 * 30)
    login_max_attempts: int = Field(5, ge=3, le=50)
    lockout_minutes: int = Field(15, ge=1, le=24 * 60)
    password_min_length: int = Field(12, ge=8, le=128)
    # None = automatic (Secure when TLS is enabled or a trusted proxy terminates TLS)
    cookie_secure: bool | None = None


class LoggingConfig(BaseModel):
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    file: str | None = None
    max_bytes: int = Field(10 * 1024 * 1024, ge=1024 * 1024)
    backup_count: int = Field(5, ge=1, le=100)
    json_format: bool = True


class MonitoringConfig(BaseModel):
    poll_interval_seconds: int = Field(30, ge=10, le=3600)
    metrics_server: bool = True
    prometheus_url: str | None = None
    prometheus_timeout: float = Field(10, gt=0, le=120)
    # Bearer token for Prometheus; prefer setting it through PKM_MONITORING__PROMETHEUS_TOKEN
    prometheus_token: str | None = None
    prometheus_verify_tls: bool = True

    @field_validator("prometheus_url")
    @classmethod
    def _check_url(cls, v: str | None) -> str | None:
        if v in (None, ""):
            return None
        if not v.startswith(("http://", "https://")):
            raise ValueError("prometheus_url must start with http:// or https://")
        return v.rstrip("/")


class BackupConfig(BaseModel):
    directory: str = "/var/lib/pkm/backups"
    retention_count: int = Field(14, ge=1, le=1000)
    include_manifests: bool = False


class AuditConfig(BaseModel):
    retention_days: int = Field(365, ge=7, le=3650)


class LogsConfig(BaseModel):
    max_tail_lines: int = Field(5000, ge=100, le=50000)
    stream_max_seconds: int = Field(1800, ge=30, le=24 * 3600)
    stream_max_lines: int = Field(20000, ge=100, le=1_000_000)
    max_concurrent_streams: int = Field(20, ge=1, le=200)


class RateLimitConfig(BaseModel):
    api_per_minute: int = Field(600, ge=30)
    login_per_minute: int = Field(10, ge=1)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PKM_", env_nested_delimiter="__", extra="ignore")

    app_name: str = "Scarlet"
    mode: Literal["live", "demo"] = "live"
    environment: Literal["production", "development"] = "production"
    server: ServerConfig = Field(default_factory=ServerConfig)
    kubernetes: KubernetesConfig = Field(default_factory=KubernetesConfig)
    podman: PodmanConfig = Field(default_factory=PodmanConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    monitoring: MonitoringConfig = Field(default_factory=MonitoringConfig)
    backup: BackupConfig = Field(default_factory=BackupConfig)
    audit: AuditConfig = Field(default_factory=AuditConfig)
    logs: LogsConfig = Field(default_factory=LogsConfig)
    rate_limit: RateLimitConfig = Field(default_factory=RateLimitConfig)

    # Path of the file the settings were loaded from (informational).
    config_file: str | None = None

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # Environment wins over the YAML file (passed as init kwargs).
        return (env_settings, init_settings, file_secret_settings)

    @model_validator(mode="after")
    def _no_demo_in_production(self) -> Settings:
        if self.mode == "demo" and self.environment == "production":
            raise ValueError(
                "mode=demo is not allowed with environment=production: demo data must never "
                "be shown as a live cluster. Set environment: development to use demo mode."
            )
        if bool(self.server.tls_cert) != bool(self.server.tls_key):
            raise ValueError("server.tls_cert and server.tls_key must be set together")
        return self

    @property
    def is_demo(self) -> bool:
        return self.mode == "demo"

    @property
    def cookie_secure(self) -> bool:
        if self.auth.cookie_secure is not None:
            return self.auth.cookie_secure
        return self.server.tls_enabled or bool(self.server.trusted_proxies)


class ConfigError(Exception):
    pass


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except OSError as exc:
        raise ConfigError(f"cannot read configuration file {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in configuration file {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"configuration file {path} must contain a mapping")
    return data


def load_settings(path: str | None = None) -> Settings:
    """Load settings from file + environment. Raises ConfigError with a readable message."""
    from pydantic import ValidationError

    cfg_path = path or os.environ.get("PKM_CONFIG")
    data: dict[str, Any] = {}
    used: str | None = None
    if cfg_path:
        data = _read_yaml(Path(cfg_path))
        used = cfg_path
    elif Path(DEFAULT_CONFIG_PATH).is_file():
        data = _read_yaml(Path(DEFAULT_CONFIG_PATH))
        used = DEFAULT_CONFIG_PATH
    try:
        settings = Settings(**data)
    except ValidationError as exc:
        lines = []
        for err in exc.errors():
            loc = ".".join(str(p) for p in err["loc"]) or "(root)"
            lines.append(f"  - {loc}: {err['msg']}")
        raise ConfigError("invalid configuration:\n" + "\n".join(lines)) from exc
    settings.config_file = used
    return settings
