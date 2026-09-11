"""Application configuration.

All configuration comes from environment variables (12-factor). Production
configuration is validated at startup and the process refuses to start when
a required secret is missing or an insecure default would be used.
"""

from __future__ import annotations

import os
import warnings
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

from app.errors import ConfigurationError

TRUE_VALUES = {"1", "true", "yes", "on"}
VALID_ENVS = {"development", "production", "testing"}
INSECURE_SECRETS = {"", "changeme", "change-me", "secret", "dev", "development", "insecure"}


def env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in TRUE_VALUES


def env_int(
    name: str, default: int, *, minimum: int | None = None, maximum: int | None = None
) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        value = default
    else:
        try:
            value = int(raw)
        except ValueError as exc:
            raise ConfigurationError(f"{name} must be an integer, got {raw!r}") from exc
    if minimum is not None and value < minimum:
        raise ConfigurationError(f"{name} must be >= {minimum}")
    if maximum is not None and value > maximum:
        raise ConfigurationError(f"{name} must be <= {maximum}")
    return value


def env_str(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


@dataclass
class Config:
    """Flat configuration object consumed by Flask (``app.config.from_object``)."""

    # --- environment -----------------------------------------------------------
    SCARLET_ENV: str = "development"
    DEBUG: bool = False
    TESTING: bool = False
    APP_VERSION: str = "1.0.0"

    # --- secrets ---------------------------------------------------------------
    SECRET_KEY: str = ""
    SCARLET_CREDENTIAL_ENCRYPTION_KEY: str = ""
    SCARLET_CREDENTIAL_ENCRYPTION_KEY_PREVIOUS: str = ""

    # --- database / redis ------------------------------------------------------
    SQLALCHEMY_DATABASE_URI: str = "sqlite:///scarlet-dev.sqlite"
    SQLALCHEMY_TRACK_MODIFICATIONS: bool = False
    SQLALCHEMY_ENGINE_OPTIONS: dict[str, Any] = field(default_factory=dict)
    REDIS_URL: str = "redis://localhost:6379/0"

    # --- celery ----------------------------------------------------------------
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/1"
    CELERY_TASK_ALWAYS_EAGER: bool = False
    CELERY_TASK_TIME_LIMIT: int = 3600

    # --- storage ---------------------------------------------------------------
    SCARLET_ARTIFACT_PATH: str = "./data/artifacts"
    SCARLET_UPLOAD_TMP_PATH: str = "./data/uploads"
    SCARLET_LOG_PATH: str = "./data/logs"
    SCARLET_MAX_UPLOAD_MB: int = 2048
    MAX_CONTENT_LENGTH: int = 2049 * 1024 * 1024
    SCARLET_MAX_PACKAGE_MEMBERS: int = 20000
    SCARLET_MAX_PACKAGE_UNCOMPRESSED_MB: int = 8192

    # --- remote layout ---------------------------------------------------------
    SCARLET_REMOTE_BASE_PATH: str = "/opt/scarlet"

    # --- ssh -------------------------------------------------------------------
    SCARLET_SSH_TIMEOUT: int = 30
    SCARLET_SSH_COMMAND_TIMEOUT: int = 600
    SCARLET_SFTP_TIMEOUT: int = 1800
    SCARLET_SSH_HOST_KEY_POLICY: str = "strict"  # strict | tofu

    # --- jobs / timeouts -------------------------------------------------------
    SCARLET_JOB_TIMEOUT: int = 3600
    SCARLET_DEPLOYMENT_TIMEOUT: int = 1800
    SCARLET_HEALTH_CHECK_TIMEOUT: int = 10
    SCARLET_HEALTH_CHECK_RETRIES: int = 5
    SCARLET_HEALTH_CHECK_INTERVAL: int = 3
    SCARLET_LOCK_TIMEOUT: int = 1800
    SCARLET_MAX_PARALLEL_DEPLOYMENTS: int = 3
    SCARLET_PROD_MAX_PARALLEL_DEPLOYMENTS: int = 1
    SCARLET_RECONCILE_INTERVAL: int = 300
    SCARLET_RECONCILE_ENABLED: bool = True
    SCARLET_RECONCILE_AUTO_REMEDIATE: bool = False

    # --- production safety -----------------------------------------------------
    SCARLET_PROD_REQUIRE_CONFIRMATION: bool = True
    SCARLET_PROD_REQUIRE_APPROVAL: bool = False
    SCARLET_PROD_ALLOW_ROLLBACK: bool = True
    SCARLET_PROD_CONFIRMATION_PHRASE: str = "DEPLOY TO PROD"
    SCARLET_PROD_REQUIRE_REASON: bool = True
    SCARLET_AUTO_ROLLBACK: bool = False
    SCARLET_ALLOW_DIAGNOSTIC_SHELL: bool = False

    # --- retention -------------------------------------------------------------
    SCARLET_ARTIFACT_RETENTION_COUNT: int = 10
    SCARLET_LOG_RETENTION_DAYS: int = 90
    SCARLET_OPERATION_LOG_RETENTION_DAYS: int = 180
    SCARLET_AUDIT_RETENTION_DAYS: int = 0  # 0 = never purge

    # --- web security ----------------------------------------------------------
    SESSION_COOKIE_SECURE: bool = True
    SESSION_COOKIE_HTTPONLY: bool = True
    SESSION_COOKIE_SAMESITE: str = "Lax"
    SESSION_COOKIE_NAME: str = "scarlet_session"
    PERMANENT_SESSION_LIFETIME: int = 8 * 3600
    REMEMBER_COOKIE_SECURE: bool = True
    REMEMBER_COOKIE_HTTPONLY: bool = True
    WTF_CSRF_ENABLED: bool = True
    WTF_CSRF_TIME_LIMIT: int | None = None
    WTF_CSRF_CHECK_DEFAULT: bool = True
    SCARLET_LOGIN_RATE_LIMIT: str = "5 per minute"
    SCARLET_API_RATE_LIMIT: str = "600 per minute"
    RATELIMIT_STORAGE_URI: str = "memory://"
    RATELIMIT_HEADERS_ENABLED: bool = True
    SCARLET_HSTS_ENABLED: bool = True
    SCARLET_TRUSTED_PROXIES: int = 1
    SCARLET_ASSET_MODE: str = "cdn"  # cdn | local
    SCARLET_API_DOCS_ENABLED: bool = True

    # --- password policy -------------------------------------------------------
    SCARLET_PASSWORD_MIN_LENGTH: int = 12
    SCARLET_PASSWORD_REQUIRE_COMPLEXITY: bool = True
    SCARLET_MAX_FAILED_LOGINS: int = 10
    SCARLET_LOCKOUT_MINUTES: int = 15

    # --- logging ---------------------------------------------------------------
    SCARLET_LOG_LEVEL: str = "INFO"
    SCARLET_LOG_FORMAT: str = "json"  # json | text

    # --- notifications ---------------------------------------------------------
    SCARLET_MAIL_ENABLED: bool = False
    SCARLET_MAIL_SERVER: str = ""
    SCARLET_MAIL_PORT: int = 587
    SCARLET_MAIL_USE_TLS: bool = True
    SCARLET_MAIL_USERNAME: str = ""
    SCARLET_MAIL_PASSWORD: str = ""
    SCARLET_MAIL_FROM: str = "scarlet@localhost"

    # --- external scanner (optional) -------------------------------------------
    SCARLET_MALWARE_SCANNER_COMMAND: str = ""

    # --- seeding ---------------------------------------------------------------
    SCARLET_INITIAL_ADMIN_PASSWORD: str = ""

    @property
    def is_production(self) -> bool:
        return self.SCARLET_ENV == "production"


def build_config(overrides: dict[str, Any] | None = None) -> Config:
    """Build configuration from environment variables, then apply overrides."""
    env_name = env_str("SCARLET_ENV", "development").strip().lower()
    if env_name not in VALID_ENVS:
        raise ConfigurationError(
            f"SCARLET_ENV must be development, production or testing (got {env_name!r})"
        )
    is_prod = env_name == "production"
    is_test = env_name == "testing"
    max_upload_mb = env_int("SCARLET_MAX_UPLOAD_MB", 2048, minimum=1, maximum=1024 * 64)
    redis_url = env_str("REDIS_URL", "redis://localhost:6379/0")
    default_db = "sqlite:///scarlet-test.sqlite" if is_test else "sqlite:///scarlet-dev.sqlite"

    cfg = Config(
        SCARLET_ENV=env_name,
        DEBUG=env_bool("SCARLET_DEBUG", False) and not is_prod,
        TESTING=is_test,
        APP_VERSION=env_str("SCARLET_VERSION", "1.0.0"),
        SECRET_KEY=env_str("SCARLET_SECRET_KEY", ""),
        SCARLET_CREDENTIAL_ENCRYPTION_KEY=env_str("SCARLET_CREDENTIAL_ENCRYPTION_KEY", ""),
        SCARLET_CREDENTIAL_ENCRYPTION_KEY_PREVIOUS=env_str(
            "SCARLET_CREDENTIAL_ENCRYPTION_KEY_PREVIOUS", ""
        ),
        SQLALCHEMY_DATABASE_URI=env_str("DATABASE_URL", default_db),
        REDIS_URL=redis_url,
        CELERY_BROKER_URL=env_str("CELERY_BROKER_URL", redis_url),
        CELERY_RESULT_BACKEND=env_str("CELERY_RESULT_BACKEND", redis_url),
        CELERY_TASK_ALWAYS_EAGER=env_bool("SCARLET_CELERY_EAGER", is_test),
        CELERY_TASK_TIME_LIMIT=env_int("SCARLET_JOB_TIMEOUT", 3600, minimum=60),
        SCARLET_ARTIFACT_PATH=env_str("SCARLET_ARTIFACT_PATH", "./data/artifacts"),
        SCARLET_UPLOAD_TMP_PATH=env_str("SCARLET_UPLOAD_TMP_PATH", "./data/uploads"),
        SCARLET_LOG_PATH=env_str("SCARLET_LOG_PATH", "./data/logs"),
        SCARLET_MAX_UPLOAD_MB=max_upload_mb,
        MAX_CONTENT_LENGTH=(max_upload_mb + 1) * 1024 * 1024,
        SCARLET_MAX_PACKAGE_MEMBERS=env_int("SCARLET_MAX_PACKAGE_MEMBERS", 20000, minimum=10),
        SCARLET_MAX_PACKAGE_UNCOMPRESSED_MB=env_int(
            "SCARLET_MAX_PACKAGE_UNCOMPRESSED_MB", 8192, minimum=1
        ),
        SCARLET_REMOTE_BASE_PATH=env_str("SCARLET_REMOTE_BASE_PATH", "/opt/scarlet"),
        SCARLET_SSH_TIMEOUT=env_int("SCARLET_SSH_TIMEOUT", 30, minimum=1, maximum=600),
        SCARLET_SSH_COMMAND_TIMEOUT=env_int("SCARLET_SSH_COMMAND_TIMEOUT", 600, minimum=1),
        SCARLET_SFTP_TIMEOUT=env_int("SCARLET_SFTP_TIMEOUT", 1800, minimum=10),
        SCARLET_SSH_HOST_KEY_POLICY=env_str("SCARLET_SSH_HOST_KEY_POLICY", "strict").lower(),
        SCARLET_JOB_TIMEOUT=env_int("SCARLET_JOB_TIMEOUT", 3600, minimum=60),
        SCARLET_DEPLOYMENT_TIMEOUT=env_int("SCARLET_DEPLOYMENT_TIMEOUT", 1800, minimum=60),
        SCARLET_HEALTH_CHECK_TIMEOUT=env_int("SCARLET_HEALTH_CHECK_TIMEOUT", 10, minimum=1),
        SCARLET_HEALTH_CHECK_RETRIES=env_int("SCARLET_HEALTH_CHECK_RETRIES", 5, minimum=1),
        SCARLET_HEALTH_CHECK_INTERVAL=env_int("SCARLET_HEALTH_CHECK_INTERVAL", 3, minimum=0),
        SCARLET_LOCK_TIMEOUT=env_int("SCARLET_LOCK_TIMEOUT", 1800, minimum=30),
        SCARLET_MAX_PARALLEL_DEPLOYMENTS=env_int("SCARLET_MAX_PARALLEL_DEPLOYMENTS", 3, minimum=1),
        SCARLET_PROD_MAX_PARALLEL_DEPLOYMENTS=env_int(
            "SCARLET_PROD_MAX_PARALLEL_DEPLOYMENTS", 1, minimum=1
        ),
        SCARLET_RECONCILE_INTERVAL=env_int("SCARLET_RECONCILE_INTERVAL", 300, minimum=30),
        SCARLET_RECONCILE_ENABLED=env_bool("SCARLET_RECONCILE_ENABLED", True),
        SCARLET_RECONCILE_AUTO_REMEDIATE=env_bool("SCARLET_RECONCILE_AUTO_REMEDIATE", False),
        SCARLET_PROD_REQUIRE_CONFIRMATION=env_bool("SCARLET_PROD_REQUIRE_CONFIRMATION", True),
        SCARLET_PROD_REQUIRE_APPROVAL=env_bool("SCARLET_PROD_REQUIRE_APPROVAL", False),
        SCARLET_PROD_ALLOW_ROLLBACK=env_bool("SCARLET_PROD_ALLOW_ROLLBACK", True),
        SCARLET_PROD_CONFIRMATION_PHRASE=env_str(
            "SCARLET_PROD_CONFIRMATION_PHRASE", "DEPLOY TO PROD"
        ),
        SCARLET_PROD_REQUIRE_REASON=env_bool("SCARLET_PROD_REQUIRE_REASON", True),
        SCARLET_AUTO_ROLLBACK=env_bool("SCARLET_AUTO_ROLLBACK", False),
        SCARLET_ALLOW_DIAGNOSTIC_SHELL=env_bool("SCARLET_ALLOW_DIAGNOSTIC_SHELL", False),
        SCARLET_ARTIFACT_RETENTION_COUNT=env_int(
            "SCARLET_ARTIFACT_RETENTION_COUNT", 10, minimum=2
        ),
        SCARLET_LOG_RETENTION_DAYS=env_int("SCARLET_LOG_RETENTION_DAYS", 90, minimum=1),
        SCARLET_OPERATION_LOG_RETENTION_DAYS=env_int(
            "SCARLET_OPERATION_LOG_RETENTION_DAYS", 180, minimum=1
        ),
        SCARLET_AUDIT_RETENTION_DAYS=env_int("SCARLET_AUDIT_RETENTION_DAYS", 0, minimum=0),
        SESSION_COOKIE_SECURE=env_bool("SESSION_COOKIE_SECURE", is_prod),
        SESSION_COOKIE_HTTPONLY=env_bool("SESSION_COOKIE_HTTPONLY", True),
        SESSION_COOKIE_SAMESITE=env_str("SESSION_COOKIE_SAMESITE", "Lax"),
        PERMANENT_SESSION_LIFETIME=env_int(
            "SCARLET_SESSION_LIFETIME_SECONDS", 8 * 3600, minimum=60
        ),
        REMEMBER_COOKIE_SECURE=env_bool("SESSION_COOKIE_SECURE", is_prod),
        WTF_CSRF_ENABLED=env_bool("SCARLET_CSRF_ENABLED", not is_test),
        SCARLET_LOGIN_RATE_LIMIT=env_str("SCARLET_LOGIN_RATE_LIMIT", "5 per minute"),
        SCARLET_API_RATE_LIMIT=env_str("SCARLET_API_RATE_LIMIT", "600 per minute"),
        RATELIMIT_STORAGE_URI=env_str(
            "SCARLET_RATELIMIT_STORAGE_URI", redis_url if is_prod else "memory://"
        ),
        SCARLET_HSTS_ENABLED=env_bool("SCARLET_HSTS_ENABLED", is_prod),
        SCARLET_TRUSTED_PROXIES=env_int("SCARLET_TRUSTED_PROXIES", 1, minimum=0, maximum=10),
        SCARLET_ASSET_MODE=env_str("SCARLET_ASSET_MODE", "cdn").lower(),
        SCARLET_API_DOCS_ENABLED=env_bool("SCARLET_API_DOCS_ENABLED", not is_prod),
        SCARLET_PASSWORD_MIN_LENGTH=env_int("SCARLET_PASSWORD_MIN_LENGTH", 12, minimum=8),
        SCARLET_PASSWORD_REQUIRE_COMPLEXITY=env_bool("SCARLET_PASSWORD_REQUIRE_COMPLEXITY", True),
        SCARLET_MAX_FAILED_LOGINS=env_int("SCARLET_MAX_FAILED_LOGINS", 10, minimum=3),
        SCARLET_LOCKOUT_MINUTES=env_int("SCARLET_LOCKOUT_MINUTES", 15, minimum=1),
        SCARLET_LOG_LEVEL=env_str("SCARLET_LOG_LEVEL", "INFO").upper(),
        SCARLET_LOG_FORMAT=env_str("SCARLET_LOG_FORMAT", "json").lower(),
        SCARLET_MAIL_ENABLED=env_bool("SCARLET_MAIL_ENABLED", False),
        SCARLET_MAIL_SERVER=env_str("SCARLET_MAIL_SERVER", ""),
        SCARLET_MAIL_PORT=env_int("SCARLET_MAIL_PORT", 587, minimum=1, maximum=65535),
        SCARLET_MAIL_USE_TLS=env_bool("SCARLET_MAIL_USE_TLS", True),
        SCARLET_MAIL_USERNAME=env_str("SCARLET_MAIL_USERNAME", ""),
        SCARLET_MAIL_PASSWORD=env_str("SCARLET_MAIL_PASSWORD", ""),
        SCARLET_MAIL_FROM=env_str("SCARLET_MAIL_FROM", "scarlet@localhost"),
        SCARLET_MALWARE_SCANNER_COMMAND=env_str("SCARLET_MALWARE_SCANNER_COMMAND", ""),
        SCARLET_INITIAL_ADMIN_PASSWORD=env_str("SCARLET_INITIAL_ADMIN_PASSWORD", ""),
    )

    if overrides:
        for key, value in overrides.items():
            setattr(cfg, key, value)

    if cfg.SQLALCHEMY_DATABASE_URI.startswith("postgresql"):
        cfg.SQLALCHEMY_ENGINE_OPTIONS = {
            "pool_pre_ping": True,
            "pool_size": env_int("SCARLET_DB_POOL_SIZE", 10, minimum=1),
            "max_overflow": env_int("SCARLET_DB_MAX_OVERFLOW", 20, minimum=0),
            "pool_recycle": 1800,
        }
        if cfg.SQLALCHEMY_DATABASE_URI.startswith("postgresql://"):
            cfg.SQLALCHEMY_DATABASE_URI = cfg.SQLALCHEMY_DATABASE_URI.replace(
                "postgresql://", "postgresql+psycopg://", 1
            )

    # Development conveniences: never applied in production.
    if not cfg.is_production and not cfg.SECRET_KEY:
        cfg.SECRET_KEY = "dev-only-insecure-secret-key-" + cfg.SCARLET_ENV
    if not cfg.is_production and not cfg.SCARLET_CREDENTIAL_ENCRYPTION_KEY:
        cfg.SCARLET_CREDENTIAL_ENCRYPTION_KEY = "dev-only-insecure-credential-key-" + cfg.SCARLET_ENV

    validate_config(cfg)
    return cfg


def validate_config(cfg: Config) -> None:
    """Fail fast on invalid or insecure configuration."""
    problems: list[str] = []

    if cfg.SCARLET_SSH_HOST_KEY_POLICY not in {"strict", "tofu"}:
        problems.append("SCARLET_SSH_HOST_KEY_POLICY must be 'strict' or 'tofu'")
    if cfg.SCARLET_LOG_FORMAT not in {"json", "text"}:
        problems.append("SCARLET_LOG_FORMAT must be 'json' or 'text'")
    if cfg.SCARLET_ASSET_MODE not in {"cdn", "local"}:
        problems.append("SCARLET_ASSET_MODE must be 'cdn' or 'local'")
    if cfg.SESSION_COOKIE_SAMESITE not in {"Lax", "Strict"}:
        problems.append("SESSION_COOKIE_SAMESITE must be 'Lax' or 'Strict'")
    base = PurePosixPath(cfg.SCARLET_REMOTE_BASE_PATH)
    if not base.is_absolute() or ".." in base.parts or str(base) == "/":
        problems.append("SCARLET_REMOTE_BASE_PATH must be an absolute path (not '/') without '..'")

    if cfg.is_production:
        if cfg.SECRET_KEY.strip().lower() in INSECURE_SECRETS or len(cfg.SECRET_KEY) < 32:
            problems.append(
                "SCARLET_SECRET_KEY must be set to a random value of at least 32 characters"
            )
        if (
            cfg.SCARLET_CREDENTIAL_ENCRYPTION_KEY.strip().lower() in INSECURE_SECRETS
            or len(cfg.SCARLET_CREDENTIAL_ENCRYPTION_KEY) < 32
        ):
            problems.append(
                "SCARLET_CREDENTIAL_ENCRYPTION_KEY must be set "
                "(generate with `flask scarlet gen-key`)"
            )
        if cfg.SECRET_KEY and cfg.SECRET_KEY == cfg.SCARLET_CREDENTIAL_ENCRYPTION_KEY:
            problems.append("SCARLET_SECRET_KEY and SCARLET_CREDENTIAL_ENCRYPTION_KEY must differ")
        if cfg.SQLALCHEMY_DATABASE_URI.startswith("sqlite"):
            problems.append("SQLite is not allowed in production; set DATABASE_URL to PostgreSQL")
        if cfg.DEBUG:
            problems.append("Debug mode must be disabled in production")
        if not cfg.SESSION_COOKIE_SECURE:
            problems.append("SESSION_COOKIE_SECURE must be true in production")
        if cfg.CELERY_TASK_ALWAYS_EAGER:
            problems.append("SCARLET_CELERY_EAGER must be false in production")
        if cfg.SCARLET_SSH_HOST_KEY_POLICY != "strict":
            problems.append("SCARLET_SSH_HOST_KEY_POLICY must be 'strict' in production")
        if cfg.SCARLET_ALLOW_DIAGNOSTIC_SHELL:
            problems.append("SCARLET_ALLOW_DIAGNOSTIC_SHELL must be false (feature not enabled)")
        if not cfg.WTF_CSRF_ENABLED:
            problems.append("CSRF protection must be enabled in production")
        if not cfg.SCARLET_PROD_REQUIRE_CONFIRMATION:
            warnings.warn(
                "SCARLET_PROD_REQUIRE_CONFIRMATION is disabled; production deployments will "
                "not require typed confirmation.",
                stacklevel=2,
            )

    if problems:
        raise ConfigurationError(
            "Invalid SCARLET configuration:\n  - " + "\n  - ".join(problems),
            details={"problems": problems},
        )
