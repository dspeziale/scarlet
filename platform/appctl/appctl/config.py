"""Manifest dell'applicazione (app.conf) e risoluzione della directory applicativa.

Formato di app.conf: righe KEY=VALUE, commenti con '#'. Nessun YAML per non dipendere da
librerie esterne e per restare leggibile agli operatori.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from appctl.errors import UsageError

APPS_ROOT = Path(os.environ.get("APPCTL_APPS_ROOT", "/opt/apps"))
NAME_RE = re.compile(r"^[a-z][a-z0-9-]{1,31}$")
TAG_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$")

REQUIRED_KEYS = ("APP_NAME", "APP_ENVIRONMENT", "IMAGE_REPOSITORY", "COMPOSE_FILES")

DEFAULTS: dict[str, str] = {
    "APP_SERVICE": "app",
    "DB_SERVICE": "",
    "APP_PORT": "8080",
    "HEALTH_URL": "",
    "READY_URL": "",
    "VERSION_URL": "",
    "HEALTH_TIMEOUT": "120",
    "HEALTH_INTERVAL": "3",
    "MIGRATE_COMMAND": "",
    "AUTO_ROLLBACK": "true",
    "KEEP_RELEASES": "5",
    "PULL_POLICY": "always",
    "BACKUP_BEFORE_MIGRATE": "false",
    "BACKUP_KEEP_DAYS": "14",
    "PUBLIC_URL": "",
    "AUDIT_LOG": "",
    "REGISTRY_HOST": "",
}


def parse_env_file(path: Path) -> dict[str, str]:
    """Legge un file KEY=VALUE (stesso formato dei file env di Docker Compose)."""
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key] = value
    return values


def _as_bool(value: str) -> bool:
    return value.strip().lower() in ("1", "true", "yes", "on")


@dataclass
class AppConfig:
    app_dir: Path
    name: str
    environment: str
    image_repository: str
    compose_files: list[str]
    app_service: str = "app"
    db_service: str = ""
    app_port: int = 8080
    health_url: str = ""
    ready_url: str = ""
    version_url: str = ""
    health_timeout: int = 120
    health_interval: int = 3
    migrate_command: str = ""
    auto_rollback: bool = True
    keep_releases: int = 5
    pull_policy: str = "always"
    backup_before_migrate: bool = False
    backup_keep_days: int = 14
    public_url: str = ""
    audit_log: Path = field(default_factory=lambda: Path("/var/log/apps/unknown/audit.log"))
    registry_host: str = ""
    raw: dict[str, str] = field(default_factory=dict)

    # ----------------------------------------------------------------- percorsi standard
    @property
    def config_dir(self) -> Path:
        return self.app_dir / "config"

    @property
    def secrets_dir(self) -> Path:
        return self.app_dir / "secrets"

    @property
    def secrets_file(self) -> Path:
        return self.secrets_dir / "app.secrets.env"

    @property
    def app_env_file(self) -> Path:
        return self.config_dir / "app.env"

    @property
    def releases_dir(self) -> Path:
        return self.app_dir / "releases"

    @property
    def current_link(self) -> Path:
        return self.app_dir / "current"

    @property
    def state_dir(self) -> Path:
        return self.app_dir / "state"

    @property
    def data_dir(self) -> Path:
        return self.app_dir / "data"

    @property
    def backups_dir(self) -> Path:
        return self.app_dir / "backups"

    @property
    def logs_dir(self) -> Path:
        return self.app_dir / "logs"

    @property
    def app_container(self) -> str:
        return f"{self.name}-{self.app_service}"

    def image_ref(self, tag: str) -> str:
        return f"{self.image_repository}:{tag}"

    def release_dir(self, tag: str) -> Path:
        return self.releases_dir / tag

    def compose_env(self, image: str) -> dict[str, str]:
        """Variabili passate a docker compose (vedi deploy/compose.yaml)."""
        return {
            "IMAGE": image,
            "APP_NAME": self.name,
            "APP_DIR": str(self.app_dir),
            "APP_PORT": str(self.app_port),
        }


def validate_tag(tag: str) -> str:
    if not TAG_RE.match(tag):
        raise UsageError(
            f"tag immagine non valido: {tag!r}",
            "formato atteso: git-<sha12> oppure vX.Y.Z (solo lettere, numeri, '.', '_', '-')",
        )
    return tag


def resolve_app_dir(app: str | None, app_dir: str | None) -> Path:
    """Determina la directory dell'applicazione.

    Ordine: --app-dir, APPCTL_APP_DIR, --app / APPCTL_APP (=> /opt/apps/<app>), oppure l'unica
    applicazione presente in /opt/apps.
    """
    if app_dir:
        return Path(app_dir).expanduser().resolve()
    env_dir = os.environ.get("APPCTL_APP_DIR")
    if env_dir:
        return Path(env_dir).expanduser().resolve()
    name = app or os.environ.get("APPCTL_APP")
    if name:
        if not NAME_RE.match(name):
            raise UsageError(f"nome applicazione non valido: {name!r}")
        return APPS_ROOT / name
    if APPS_ROOT.is_dir():
        candidates = sorted(p for p in APPS_ROOT.iterdir() if (p / "app.conf").is_file())
        if len(candidates) == 1:
            return candidates[0]
        if len(candidates) > 1:
            names = ", ".join(p.name for p in candidates)
            raise UsageError(
                "piu' applicazioni installate: specificare --app <nome>",
                f"applicazioni disponibili: {names}",
            )
    raise UsageError(
        f"nessuna applicazione trovata in {APPS_ROOT}",
        "usare --app <nome> oppure --app-dir <directory>",
    )


def load_config(app_dir: Path) -> AppConfig:
    conf_path = app_dir / "app.conf"
    if not conf_path.is_file():
        raise UsageError(
            f"manifest non trovato: {conf_path}",
            "installare l'applicazione con platform/server/install-app.sh",
        )
    raw = {**DEFAULTS, **parse_env_file(conf_path)}
    missing = [k for k in REQUIRED_KEYS if not raw.get(k)]
    if missing:
        raise UsageError(f"{conf_path}: chiavi obbligatorie mancanti: {', '.join(missing)}")
    if not NAME_RE.match(raw["APP_NAME"]):
        raise UsageError(f"{conf_path}: APP_NAME non valido: {raw['APP_NAME']!r}")
    if raw["APP_ENVIRONMENT"] not in ("development", "production"):
        raise UsageError(
            f"{conf_path}: APP_ENVIRONMENT deve essere development o production, non {raw['APP_ENVIRONMENT']!r}"
        )
    if raw["PULL_POLICY"] not in ("always", "missing"):
        raise UsageError(f"{conf_path}: PULL_POLICY deve essere 'always' o 'missing'")

    port = int(raw["APP_PORT"])
    base = f"http://127.0.0.1:{port}"
    audit_default = Path("/var/log/apps") / raw["APP_NAME"] / "audit.log"
    registry_host = raw["REGISTRY_HOST"] or raw["IMAGE_REPOSITORY"].split("/")[0]

    return AppConfig(
        app_dir=app_dir,
        name=raw["APP_NAME"],
        environment=raw["APP_ENVIRONMENT"],
        image_repository=raw["IMAGE_REPOSITORY"],
        compose_files=[f for f in raw["COMPOSE_FILES"].split(":") if f],
        app_service=raw["APP_SERVICE"],
        db_service=raw["DB_SERVICE"],
        app_port=port,
        health_url=raw["HEALTH_URL"] or f"{base}/health",
        ready_url=raw["READY_URL"] or f"{base}/ready",
        version_url=raw["VERSION_URL"] or f"{base}/version",
        health_timeout=int(raw["HEALTH_TIMEOUT"]),
        health_interval=max(1, int(raw["HEALTH_INTERVAL"])),
        migrate_command=raw["MIGRATE_COMMAND"],
        auto_rollback=_as_bool(raw["AUTO_ROLLBACK"]),
        keep_releases=max(2, int(raw["KEEP_RELEASES"])),
        pull_policy=raw["PULL_POLICY"],
        backup_before_migrate=_as_bool(raw["BACKUP_BEFORE_MIGRATE"]),
        backup_keep_days=int(raw["BACKUP_KEEP_DAYS"]),
        public_url=raw["PUBLIC_URL"],
        audit_log=Path(raw["AUDIT_LOG"]) if raw["AUDIT_LOG"] else audit_default,
        registry_host=registry_host,
        raw=raw,
    )
