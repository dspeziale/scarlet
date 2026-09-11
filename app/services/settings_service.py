"""System settings: database-backed overrides of environment configuration."""

from __future__ import annotations

from typing import Any

from flask import current_app

from app.audit import audit
from app.errors import NotFoundError, ValidationError
from app.extensions import db
from app.models.system import SystemSetting

# key -> (type, category, description, min, max)
SETTING_DEFINITIONS: dict[str, dict[str, Any]] = {
    "SCARLET_SSH_TIMEOUT": {
        "type": "int",
        "category": "ssh",
        "description": "SSH connect timeout (seconds)",
        "min": 1,
        "max": 600,
    },
    "SCARLET_SSH_COMMAND_TIMEOUT": {
        "type": "int",
        "category": "ssh",
        "description": "Default remote command timeout (seconds)",
        "min": 5,
        "max": 7200,
    },
    "SCARLET_DEPLOYMENT_TIMEOUT": {
        "type": "int",
        "category": "deployment",
        "description": "Deployment timeout (seconds)",
        "min": 60,
        "max": 86400,
    },
    "SCARLET_HEALTH_CHECK_TIMEOUT": {
        "type": "int",
        "category": "health",
        "description": "Health probe timeout (seconds)",
        "min": 1,
        "max": 300,
    },
    "SCARLET_HEALTH_CHECK_RETRIES": {
        "type": "int",
        "category": "health",
        "description": "Default health check retries",
        "min": 1,
        "max": 50,
    },
    "SCARLET_HEALTH_CHECK_INTERVAL": {
        "type": "int",
        "category": "health",
        "description": "Seconds between health retries",
        "min": 0,
        "max": 300,
    },
    "SCARLET_MAX_UPLOAD_MB": {
        "type": "int",
        "category": "packages",
        "description": "Maximum package upload size (MB); the web server limit must be >= this",
        "min": 1,
        "max": 65536,
    },
    "SCARLET_ARTIFACT_RETENTION_COUNT": {
        "type": "int",
        "category": "retention",
        "description": "Releases to keep per application (current and previous are always kept)",
        "min": 2,
        "max": 500,
    },
    "SCARLET_LOG_RETENTION_DAYS": {
        "type": "int",
        "category": "retention",
        "description": "Days to keep health check records",
        "min": 1,
        "max": 3650,
    },
    "SCARLET_OPERATION_LOG_RETENTION_DAYS": {
        "type": "int",
        "category": "retention",
        "description": "Days to keep operation logs",
        "min": 1,
        "max": 3650,
    },
    "SCARLET_PROD_REQUIRE_CONFIRMATION": {
        "type": "bool",
        "category": "production",
        "description": "Require typed confirmation for PROD operations",
    },
    "SCARLET_PROD_REQUIRE_APPROVAL": {
        "type": "bool",
        "category": "production",
        "description": "Require second-person approval for PROD deployments",
    },
    "SCARLET_PROD_ALLOW_ROLLBACK": {
        "type": "bool",
        "category": "production",
        "description": "Allow rollback on PROD",
    },
    "SCARLET_PROD_REQUIRE_REASON": {
        "type": "bool",
        "category": "production",
        "description": "Require a reason for PROD operations",
    },
    "SCARLET_PROD_CONFIRMATION_PHRASE": {
        "type": "str",
        "category": "production",
        "description": "Phrase to type for PROD deployments",
        "max_len": 64,
    },
    "SCARLET_AUTO_ROLLBACK": {
        "type": "bool",
        "category": "deployment",
        "description": "Automatically roll back when a deployment fails after activation",
    },
    "SCARLET_MAX_PARALLEL_DEPLOYMENTS": {
        "type": "int",
        "category": "deployment",
        "description": "Maximum concurrent deployments (non-PROD)",
        "min": 1,
        "max": 50,
    },
    "SCARLET_PROD_MAX_PARALLEL_DEPLOYMENTS": {
        "type": "int",
        "category": "deployment",
        "description": "Maximum concurrent deployments on PROD",
        "min": 1,
        "max": 20,
    },
    "SCARLET_RECONCILE_ENABLED": {
        "type": "bool",
        "category": "reconciliation",
        "description": "Enable periodic reconciliation of actual state",
    },
    "SCARLET_RECONCILE_AUTO_REMEDIATE": {
        "type": "bool",
        "category": "reconciliation",
        "description": "Allow the reconciler to change remote state toward desired state (DEV only recommended)",
    },
    "SCARLET_RECONCILE_INTERVAL": {
        "type": "int",
        "category": "reconciliation",
        "description": "Reconciliation interval (seconds)",
        "min": 30,
        "max": 86400,
    },
}


class SettingsService:
    def __init__(self, session=None) -> None:
        self.session = session or db.session
        self._cache: dict[str, Any] | None = None

    def _load(self) -> dict[str, Any]:
        if self._cache is None:
            rows = self.session.execute(db.select(SystemSetting)).scalars()
            self._cache = {row.key: row.typed_value() for row in rows}
        return self._cache

    def invalidate(self) -> None:
        self._cache = None

    def get(self, key: str, default: Any = None) -> Any:
        try:
            values = self._load()
        except (
            Exception
        ):  # noqa: BLE001 - settings must never break callers (e.g. before migrations)
            values = {}
        if key in values:
            return values[key]
        return current_app.config.get(key, default)

    def all(self) -> list[dict[str, Any]]:
        stored = {row.key: row for row in self.session.execute(db.select(SystemSetting)).scalars()}
        out = []
        for key, definition in SETTING_DEFINITIONS.items():
            row = stored.get(key)
            out.append(
                {
                    "key": key,
                    "value": row.typed_value() if row else current_app.config.get(key),
                    "default": current_app.config.get(key),
                    "overridden": row is not None,
                    "value_type": definition["type"],
                    "category": definition["category"],
                    "description": definition["description"],
                    "updated_at": row.updated_at.isoformat() if row else None,
                }
            )
        return out

    def set(self, key: str, value: Any, *, user=None) -> SystemSetting:
        definition = SETTING_DEFINITIONS.get(key)
        if definition is None:
            raise NotFoundError(f"Unknown setting {key}.")
        value_type = definition["type"]
        if value_type == "int":
            try:
                number = int(value)
            except (TypeError, ValueError) as exc:
                raise ValidationError(
                    f"{key} must be an integer.", errors={key: ["Integer required."]}
                ) from exc
            if number < definition.get("min", -(10**9)) or number > definition.get("max", 10**9):
                raise ValidationError(
                    f"{key} out of range.",
                    errors={key: [f"Must be between {definition['min']} and {definition['max']}."]},
                )
            stored = str(number)
        elif value_type == "bool":
            if isinstance(value, bool):
                stored = "true" if value else "false"
            else:
                lowered = str(value).strip().lower()
                if lowered not in {"true", "false", "1", "0", "yes", "no", "on", "off"}:
                    raise ValidationError(
                        f"{key} must be a boolean.", errors={key: ["Boolean required."]}
                    )
                stored = "true" if lowered in {"true", "1", "yes", "on"} else "false"
        else:
            stored = str(value).strip()
            if not stored or len(stored) > definition.get("max_len", 255) or "\n" in stored:
                raise ValidationError(f"{key} is invalid.", errors={key: ["Invalid value."]})
        row = self.session.execute(
            db.select(SystemSetting).where(SystemSetting.key == key)
        ).scalar_one_or_none()
        previous = row.typed_value() if row else current_app.config.get(key)
        if row is None:
            row = SystemSetting(
                key=key,
                value=stored,
                value_type=value_type,
                description=definition["description"],
                category=definition["category"],
            )
            self.session.add(row)
        else:
            row.value = stored
            row.value_type = value_type
        row.updated_by_id = getattr(user, "id", None)
        self.session.commit()
        self.invalidate()
        audit.record(
            "SETTING_UPDATED",
            user=user,
            entity_type="SystemSetting",
            entity_id=key,
            details={"key": key, "previous": previous, "new": row.typed_value()},
        )
        return row

    def reset(self, key: str, *, user=None) -> None:
        row = self.session.execute(
            db.select(SystemSetting).where(SystemSetting.key == key)
        ).scalar_one_or_none()
        if row is not None:
            self.session.delete(row)
            self.session.commit()
            self.invalidate()
            audit.record("SETTING_RESET", user=user, entity_type="SystemSetting", entity_id=key)


def get_settings_service() -> SettingsService:
    service = current_app.extensions.get("scarlet_settings_service")
    if service is None:
        service = SettingsService()
        current_app.extensions["scarlet_settings_service"] = service
    service.invalidate()
    return service
