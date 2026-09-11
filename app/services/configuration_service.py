"""Application configuration per environment with encrypted secrets and versioning."""

from __future__ import annotations

import hashlib
from typing import Any

from app.audit import audit
from app.errors import NotFoundError, ValidationError
from app.extensions import db
from app.models.application import Application
from app.models.configuration import Configuration, ConfigurationEntry, ConfigurationVersion
from app.models.enums import ConfigValueType
from app.models.host import Environment
from app.security.secrets import get_secret_provider
from app.security.validators import validate_env_key
from app.utils.time import utcnow

MAX_VALUE_LEN = 8192


class ConfigurationService:
    def get_or_create(self, application: Application, environment: Environment) -> Configuration:
        config = db.session.execute(
            db.select(Configuration).where(
                Configuration.application_id == application.id,
                Configuration.environment_id == environment.id,
            )
        ).scalar_one_or_none()
        if config is None:
            config = Configuration(application_id=application.id, environment_id=environment.id)
            db.session.add(config)
            db.session.commit()
        return config

    def get(self, application: Application, environment: Environment) -> Configuration | None:
        return db.session.execute(
            db.select(Configuration).where(
                Configuration.application_id == application.id,
                Configuration.environment_id == environment.id,
            )
        ).scalar_one_or_none()

    def set_entries(
        self,
        config: Configuration,
        entries: list[dict[str, Any]],
        *,
        user=None,
        change_summary: str = "",
    ) -> ConfigurationVersion:
        """Upsert entries. ``entries`` items: {key, value, value_type, description}.

        For secrets, an empty/None value means "keep existing".
        """
        provider = get_secret_provider()
        existing = {e.key: e for e in config.entries}
        changed: list[str] = []
        for item in entries:
            key = validate_env_key(str(item.get("key", "")))
            vtype = ConfigValueType.parse(item.get("value_type", "CONFIG"))
            if vtype is None:
                raise ValidationError(
                    "Invalid value type.", errors={"value_type": ["CONFIG or SECRET."]}
                )
            value = item.get("value")
            description = str(item.get("description") or "")[:255]
            if value is not None:
                value = str(value)
                if len(value) > MAX_VALUE_LEN or "\x00" in value or "\n" in value:
                    raise ValidationError(
                        f"Invalid value for {key}.", errors={key: ["Single line, max 8 KiB."]}
                    )
            entry = existing.get(key)
            if entry is None:
                if value is None or (value == "" and vtype == ConfigValueType.SECRET):
                    raise ValidationError(
                        f"Value required for new key {key}.", errors={key: ["Required."]}
                    )
                entry = ConfigurationEntry(
                    configuration_id=config.id,
                    key=key,
                    value_type=vtype.value,
                    description=description,
                )
                db.session.add(entry)
                changed.append(key)
            else:
                if entry.value_type != vtype.value:
                    entry.value_type = vtype.value
                    entry.value = None
                    entry.encrypted_value = None
                    changed.append(key)
                entry.description = description or entry.description
            if vtype == ConfigValueType.SECRET:
                if value:
                    entry.encrypted_value = provider.store(value)
                    entry.value = None
                    changed.append(key)
            elif value is not None and value != entry.value:
                entry.value = value
                entry.encrypted_value = None
                changed.append(key)
            entry.updated_by_id = getattr(user, "id", None)
        db.session.flush()
        version = self._snapshot(
            config,
            user=user,
            change_summary=change_summary or f"Updated {len(set(changed))} key(s)",
        )
        audit.record(
            "CONFIGURATION_UPDATED",
            user=user,
            application=config.application,
            environment=config.environment.code,
            entity_type="Configuration",
            entity_id=config.id,
            details={"keys": sorted(set(changed)), "version": version.version_number},
        )
        return version

    def delete_entry(self, config: Configuration, key: str, *, user=None) -> ConfigurationVersion:
        entry = next((e for e in config.entries if e.key == key), None)
        if entry is None:
            raise NotFoundError(f"Key {key} not found.")
        db.session.delete(entry)
        db.session.flush()
        db.session.refresh(config)
        version = self._snapshot(config, user=user, change_summary=f"Removed {key}")
        audit.record(
            "CONFIGURATION_UPDATED",
            user=user,
            application=config.application,
            environment=config.environment.code,
            entity_type="Configuration",
            entity_id=config.id,
            details={"removed": key, "version": version.version_number},
        )
        return version

    def _snapshot(
        self, config: Configuration, *, user=None, change_summary: str
    ) -> ConfigurationVersion:
        snapshot: dict[str, Any] = {}
        for entry in config.entries:
            if entry.is_secret:
                digest = hashlib.sha256((entry.encrypted_value or "").encode()).hexdigest()[:16]
                snapshot[entry.key] = {"type": "SECRET", "sha256": digest}
            else:
                snapshot[entry.key] = {"type": "CONFIG", "value": entry.value}
        for old in config.versions:
            old.is_current = False
        config.current_version_number += 1
        version = ConfigurationVersion(
            configuration_id=config.id,
            version_number=config.current_version_number,
            created_at=utcnow(),
            created_by_id=getattr(user, "id", None),
            change_summary=change_summary[:500],
            snapshot=snapshot,
            is_current=True,
        )
        db.session.add(version)
        db.session.commit()
        return version

    # --- rendering for deployments ---------------------------------------------------------------
    def render_environment(
        self,
        application: Application,
        environment: Environment,
        manifest: dict[str, Any],
        *,
        extra: dict[str, str] | None = None,
    ) -> tuple[dict[str, str], list[str]]:
        """Merge manifest defaults + configuration + decrypted secrets.

        Returns (env, missing_secrets). Secrets declared in the manifest that are
        not configured are reported so pre-flight can fail early.
        """
        env: dict[str, str] = dict(manifest.get("environment") or {})
        config = self.get(application, environment)
        provider = get_secret_provider()
        if config is not None:
            for entry in config.entries:
                if entry.is_secret:
                    if entry.encrypted_value:
                        env[entry.key] = provider.retrieve(entry.encrypted_value)
                elif entry.value is not None:
                    env[entry.key] = entry.value
        missing = [name for name in manifest.get("secrets") or [] if name not in env]
        if extra:
            env.update(extra)
        return env, missing

    @staticmethod
    def render_env_file(env: dict[str, str]) -> str:
        """Render KEY=value lines for ``--env-file`` (values are single line by validation)."""
        lines = []
        for key in sorted(env):
            value = env[key].replace("\r", "").replace("\n", "")
            lines.append(f"{key}={value}")
        return "\n".join(lines) + "\n"

    def versions(self, config: Configuration) -> list[ConfigurationVersion]:
        return list(config.versions)
