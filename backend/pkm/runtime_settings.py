"""Settings editable from the UI (Impostazioni), stored in the database on top of the file configuration.

Only the keys in EDITABLE can be changed at runtime; everything that affects how the
process starts (bind address, TLS, database path, mode) stays in config.yaml.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from .config import Settings
from .db import Database, iso
from .errors import ValidationFailed

# section -> keys editable from the UI
EDITABLE: dict[str, set[str]] = {
    "kubernetes": {"enabled", "kubeconfig", "context", "in_cluster", "request_timeout", "cache_ttl_seconds"},
    "podman": {"enabled", "url", "timeout"},
    "monitoring": {"poll_interval_seconds", "metrics_server", "prometheus_url", "prometheus_timeout",
                   "prometheus_verify_tls"},
    "logging": {"level"},
    "backup": {"retention_count", "include_manifests"},
    "audit": {"retention_days"},
    "auth": {"session_idle_minutes", "session_absolute_hours", "login_max_attempts", "lockout_minutes",
             "password_min_length"},
    "logs": {"max_tail_lines", "stream_max_seconds", "stream_max_lines"},
}  # fmt: skip
# Never returned to the browser.
SECRET_KEYS = {("monitoring", "prometheus_token")}


class RuntimeSettings:
    def __init__(self, db: Database, base: Settings) -> None:
        self.db = db
        self.base = base

    def overrides(self) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        with self.db.connect() as c:
            for row in c.execute("SELECT key, value FROM settings"):
                section, _, key = row["key"].partition(".")
                if section in EDITABLE and key in EDITABLE[section]:
                    out.setdefault(section, {})[key] = json.loads(row["value"])
        return out

    def effective(self) -> Settings:
        data = self.base.model_dump()
        for section, values in self.overrides().items():
            data[section].update(values)
        eff = Settings.model_validate(data)
        eff.config_file = self.base.config_file
        return eff

    def update(self, section: str, values: dict[str, Any], actor: str) -> Settings:
        if section not in EDITABLE:
            raise ValidationFailed(f"section '{section}' cannot be changed from the UI", params={"field": section})
        unknown = set(values) - EDITABLE[section]
        if unknown:
            raise ValidationFailed(f"keys not editable: {', '.join(sorted(unknown))}", params={"fields": sorted(unknown)})
        # Validate the candidate configuration as a whole before saving anything.
        data = self.effective().model_dump()
        data[section].update(values)
        try:
            Settings.model_validate(data)
        except ValidationError as exc:
            errs = [{"field": ".".join(str(p) for p in e["loc"]), "message": e["msg"]} for e in exc.errors()]
            raise ValidationFailed("invalid settings", params={"errors": errs}) from exc
        with self.db.transaction() as c:
            for k, v in values.items():
                c.execute(
                    "INSERT INTO settings(key, value, updated_at, updated_by) VALUES (?,?,?,?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at, "
                    "updated_by=excluded.updated_by",
                    (f"{section}.{k}", json.dumps(v), iso(), actor),
                )
        return self.effective()

    def reset(self, section: str, actor: str) -> Settings:
        with self.db.connect() as c:
            c.execute("DELETE FROM settings WHERE key LIKE ?", (f"{section}.%",))
        return self.effective()

    def describe(self) -> dict[str, Any]:
        """Effective values with their source, secrets masked."""
        eff = self.effective().model_dump()
        ov = self.overrides()
        out: dict[str, Any] = {}
        for section, values in eff.items():
            if not isinstance(values, dict):
                continue
            out[section] = {}
            for k, v in values.items():
                if (section, k) in SECRET_KEYS:
                    v = "********" if v else None
                out[section][k] = {
                    "value": v,
                    "source": "ui" if k in ov.get(section, {}) else "file",
                    "editable": k in EDITABLE.get(section, set()),
                }
        return out
