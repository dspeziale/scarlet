"""Concrete repositories (query layer). Services use these instead of raw queries."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Select, func
from sqlalchemy.orm import selectinload

from app.extensions import db
from app.models import (
    Application,
    ApplicationInstance,
    ApplicationVersion,
    AuditLog,
    Deployment,
    Environment,
    HostGroup,
    LifecycleOperation,
    Notification,
    Package,
    Role,
    SecurityEvent,
    TargetHost,
    User,
)
from app.repositories.base import Page, Repository


class UserRepository(Repository[User]):
    model = User
    default_sort = "username"
    sortable = {
        "id": User.id,
        "username": User.username,
        "created_at": User.created_at,
        "last_login_at": User.last_login_at,
    }
    searchable = [User.username, User.email, User.full_name]

    def by_username(self, username: str) -> User | None:
        return self.session.execute(
            db.select(User).where(func.lower(User.username) == username.lower())
        ).scalar_one_or_none()

    def by_email(self, email: str) -> User | None:
        return self.session.execute(
            db.select(User).where(func.lower(User.email) == email.lower())
        ).scalar_one_or_none()


class RoleRepository(Repository[Role]):
    model = Role
    default_sort = "name"
    sortable = {"id": Role.id, "name": Role.name}

    def by_name(self, name: str) -> Role | None:
        return self.session.execute(db.select(Role).where(Role.name == name)).scalar_one_or_none()


class EnvironmentRepository(Repository[Environment]):
    model = Environment
    default_sort = "sort_order"
    sortable = {
        "id": Environment.id,
        "code": Environment.code,
        "sort_order": Environment.sort_order,
    }

    def by_code(self, code: str) -> Environment | None:
        return self.session.execute(
            db.select(Environment).where(Environment.code == code.upper())
        ).scalar_one_or_none()


class HostGroupRepository(Repository[HostGroup]):
    model = HostGroup
    default_sort = "name"
    sortable = {"id": HostGroup.id, "name": HostGroup.name}
    searchable = [HostGroup.name, HostGroup.description]

    def by_name(self, name: str) -> HostGroup | None:
        return self.session.execute(
            db.select(HostGroup).where(HostGroup.name == name)
        ).scalar_one_or_none()


class HostRepository(Repository[TargetHost]):
    model = TargetHost
    default_sort = "name"
    sortable = {
        "id": TargetHost.id,
        "name": TargetHost.name,
        "hostname": TargetHost.hostname,
        "status": TargetHost.status,
        "runtime_type": TargetHost.runtime_type,
        "last_seen_at": TargetHost.last_seen_at,
        "created_at": TargetHost.created_at,
    }
    searchable = [
        TargetHost.name,
        TargetHost.hostname,
        TargetHost.ip_address,
        TargetHost.description,
    ]

    def base_query(self) -> Select:
        return db.select(TargetHost).options(
            selectinload(TargetHost.environment),
            selectinload(TargetHost.groups),
            selectinload(TargetHost.credentials),
        )

    def apply_filters(self, stmt: Select, filters: dict[str, Any]) -> Select:
        env = filters.pop("environment", None)
        if env:
            stmt = stmt.join(TargetHost.environment).where(Environment.code == str(env).upper())
        status = filters.pop("status", None)
        if status:
            if str(status).upper() == "DISABLED":
                stmt = stmt.where(TargetHost.enabled.is_(False))
            else:
                stmt = stmt.where(
                    TargetHost.status == str(status).upper(), TargetHost.enabled.is_(True)
                )
        group_id = filters.pop("group_id", None)
        if group_id:
            stmt = stmt.where(TargetHost.groups.any(HostGroup.id == int(group_id)))
        return super().apply_filters(stmt, filters)

    def by_name(self, name: str) -> TargetHost | None:
        return self.session.execute(
            db.select(TargetHost).where(TargetHost.name == name)
        ).scalar_one_or_none()

    def enabled(self) -> list[TargetHost]:
        return list(
            self.session.execute(
                self.base_query().where(TargetHost.enabled.is_(True)).order_by(TargetHost.name)
            )
            .scalars()
            .unique()
        )

    def counts_by_environment(self) -> dict[str, int]:
        rows = self.session.execute(
            db.select(Environment.code, func.count(TargetHost.id))
            .join(TargetHost.environment)
            .group_by(Environment.code)
        ).all()
        return {code: count for code, count in rows}


class ApplicationRepository(Repository[Application]):
    model = Application
    default_sort = "name"
    sortable = {
        "id": Application.id,
        "name": Application.name,
        "code": Application.code,
        "runtime_type": Application.runtime_type,
        "created_at": Application.created_at,
    }
    searchable = [Application.name, Application.code, Application.description, Application.owner]

    def by_code(self, code: str) -> Application | None:
        return self.session.execute(
            db.select(Application).where(Application.code == code.lower())
        ).scalar_one_or_none()


class VersionRepository(Repository[ApplicationVersion]):
    model = ApplicationVersion
    default_sort = "id"
    sortable = {
        "id": ApplicationVersion.id,
        "version": ApplicationVersion.version,
        "created_at": ApplicationVersion.created_at,
    }
    searchable = [ApplicationVersion.version]

    def for_application(self, application_id: int) -> list[ApplicationVersion]:
        versions = list(
            self.session.execute(
                db.select(ApplicationVersion).where(
                    ApplicationVersion.application_id == application_id
                )
            ).scalars()
        )
        return sorted(versions, key=lambda v: v.sort_key, reverse=True)

    def by_app_and_version(self, application_id: int, version: str) -> ApplicationVersion | None:
        return self.session.execute(
            db.select(ApplicationVersion).where(
                ApplicationVersion.application_id == application_id,
                ApplicationVersion.version == version,
            )
        ).scalar_one_or_none()

    def by_checksum(self, checksum: str) -> ApplicationVersion | None:
        return self.session.execute(
            db.select(ApplicationVersion).where(ApplicationVersion.checksum_sha256 == checksum)
        ).scalar_one_or_none()


class PackageRepository(Repository[Package]):
    model = Package
    default_sort = "created_at"
    sortable = {
        "id": Package.id,
        "created_at": Package.created_at,
        "status": Package.status,
        "size_bytes": Package.size_bytes,
    }
    searchable = [
        Package.original_filename,
        Package.manifest_application,
        Package.manifest_version,
        Package.checksum_sha256,
    ]

    def base_query(self) -> Select:
        return db.select(Package).options(
            selectinload(Package.application),
            selectinload(Package.version),
            selectinload(Package.uploaded_by),
        )

    def by_checksum(self, checksum: str) -> Package | None:
        return self.session.execute(
            db.select(Package).where(Package.checksum_sha256 == checksum)
        ).scalar_one_or_none()


class InstanceRepository(Repository[ApplicationInstance]):
    model = ApplicationInstance
    default_sort = "id"
    sortable = {
        "id": ApplicationInstance.id,
        "actual_state": ApplicationInstance.actual_state,
        "health_status": ApplicationInstance.health_status,
        "updated_at": ApplicationInstance.updated_at,
    }

    def base_query(self) -> Select:
        return db.select(ApplicationInstance).options(
            selectinload(ApplicationInstance.application),
            selectinload(ApplicationInstance.host).selectinload(TargetHost.environment),
            selectinload(ApplicationInstance.current_version),
            selectinload(ApplicationInstance.desired_version),
            selectinload(ApplicationInstance.previous_version),
        )

    def get_for(self, application_id: int, host_id: int) -> ApplicationInstance | None:
        return self.session.execute(
            self.base_query().where(
                ApplicationInstance.application_id == application_id,
                ApplicationInstance.host_id == host_id,
            )
        ).scalar_one_or_none()

    def get_or_create(self, application_id: int, host_id: int) -> ApplicationInstance:
        instance = self.get_for(application_id, host_id)
        if instance is None:
            instance = ApplicationInstance(application_id=application_id, host_id=host_id)
            self.session.add(instance)
            self.session.flush()
        return instance

    def for_application(self, application_id: int) -> list[ApplicationInstance]:
        return list(
            self.session.execute(
                self.base_query().where(ApplicationInstance.application_id == application_id)
            )
            .scalars()
            .unique()
        )

    def for_host(self, host_id: int) -> list[ApplicationInstance]:
        return list(
            self.session.execute(self.base_query().where(ApplicationInstance.host_id == host_id))
            .scalars()
            .unique()
        )

    def all_active(self) -> list[ApplicationInstance]:
        return list(
            self.session.execute(
                self.base_query().join(ApplicationInstance.host).where(TargetHost.enabled.is_(True))
            )
            .scalars()
            .unique()
        )

    def counts_by_state(self) -> dict[str, int]:
        rows = self.session.execute(
            db.select(
                ApplicationInstance.actual_state, func.count(ApplicationInstance.id)
            ).group_by(ApplicationInstance.actual_state)
        ).all()
        return {state: count for state, count in rows}


class DeploymentRepository(Repository[Deployment]):
    model = Deployment
    default_sort = "created_at"
    sortable = {
        "id": Deployment.id,
        "created_at": Deployment.created_at,
        "status": Deployment.status,
        "completed_at": Deployment.completed_at,
        "reference": Deployment.reference,
    }
    searchable = [Deployment.reference, Deployment.reason]

    def base_query(self) -> Select:
        return db.select(Deployment).options(
            selectinload(Deployment.application),
            selectinload(Deployment.version),
            selectinload(Deployment.previous_version),
            selectinload(Deployment.target),
            selectinload(Deployment.environment),
            selectinload(Deployment.requested_by),
            selectinload(Deployment.approvals),
            selectinload(Deployment.batch),
        )

    def apply_filters(self, stmt: Select, filters: dict[str, Any]) -> Select:
        env = filters.pop("environment", None)
        if env:
            stmt = stmt.join(Deployment.environment).where(Environment.code == str(env).upper())
        status = filters.pop("status", None)
        if status:
            from app.models.enums import DeploymentStatus

            wanted = str(status).upper()
            matching = [
                s.value for s in DeploymentStatus if s.value == wanted or s.summary == wanted
            ]
            stmt = stmt.where(Deployment.status.in_(matching))
        date_from = filters.pop("date_from", None)
        if date_from:
            stmt = stmt.where(Deployment.created_at >= _parse_date(date_from))
        date_to = filters.pop("date_to", None)
        if date_to:
            stmt = stmt.where(Deployment.created_at < _parse_date(date_to, end=True))
        return super().apply_filters(stmt, filters)

    def by_reference(self, reference: str) -> Deployment | None:
        return self.session.execute(
            self.base_query().where(Deployment.reference == reference)
        ).scalar_one_or_none()

    def next_sequence(self) -> int:
        return (self.session.execute(db.select(func.max(Deployment.id))).scalar() or 0) + 1

    def active_for(self, application_id: int, target_id: int) -> list[Deployment]:
        from app.models.enums import TERMINAL_DEPLOYMENT_STATES

        terminal = [s.value for s in TERMINAL_DEPLOYMENT_STATES]
        return list(
            self.session.execute(
                db.select(Deployment).where(
                    Deployment.application_id == application_id,
                    Deployment.target_id == target_id,
                    Deployment.status.not_in(terminal),
                )
            ).scalars()
        )

    def running_count(self, environment_id: int | None = None) -> int:
        from app.models.enums import TERMINAL_DEPLOYMENT_STATES, DeploymentStatus

        excluded = [s.value for s in TERMINAL_DEPLOYMENT_STATES] + [
            DeploymentStatus.CREATED.value,
            DeploymentStatus.PENDING_APPROVAL.value,
        ]
        stmt = db.select(func.count(Deployment.id)).where(Deployment.status.not_in(excluded))
        if environment_id:
            stmt = stmt.where(Deployment.environment_id == environment_id)
        return self.session.execute(stmt).scalar_one()

    def stats_since(self, since: datetime) -> dict[str, int]:
        from app.models.enums import FAILED_DEPLOYMENT_STATES, DeploymentStatus

        total = self.session.execute(
            db.select(func.count(Deployment.id)).where(Deployment.created_at >= since)
        ).scalar_one()
        success = self.session.execute(
            db.select(func.count(Deployment.id)).where(
                Deployment.created_at >= since, Deployment.status == DeploymentStatus.SUCCESS.value
            )
        ).scalar_one()
        failed = self.session.execute(
            db.select(func.count(Deployment.id)).where(
                Deployment.created_at >= since,
                Deployment.status.in_([s.value for s in FAILED_DEPLOYMENT_STATES]),
            )
        ).scalar_one()
        return {"total": total, "success": success, "failed": failed}

    def recent(self, limit: int = 10) -> list[Deployment]:
        return list(
            self.session.execute(
                self.base_query().order_by(Deployment.created_at.desc()).limit(limit)
            )
            .scalars()
            .unique()
        )

    def history_for_instance(
        self, application_id: int, target_id: int, limit: int = 50
    ) -> list[Deployment]:
        return list(
            self.session.execute(
                self.base_query()
                .where(
                    Deployment.application_id == application_id, Deployment.target_id == target_id
                )
                .order_by(Deployment.created_at.desc())
                .limit(limit)
            )
            .scalars()
            .unique()
        )


class OperationRepository(Repository[LifecycleOperation]):
    model = LifecycleOperation
    default_sort = "created_at"
    sortable = {
        "id": LifecycleOperation.id,
        "created_at": LifecycleOperation.created_at,
        "status": LifecycleOperation.status,
        "operation_type": LifecycleOperation.operation_type,
    }
    searchable = [LifecycleOperation.reference, LifecycleOperation.reason]

    def base_query(self) -> Select:
        return db.select(LifecycleOperation).options(
            selectinload(LifecycleOperation.application),
            selectinload(LifecycleOperation.target),
            selectinload(LifecycleOperation.requested_by),
        )

    def apply_filters(self, stmt: Select, filters: dict[str, Any]) -> Select:
        status = filters.pop("status", None)
        if status:
            stmt = stmt.where(LifecycleOperation.status == str(status).upper())
        op_type = filters.pop("operation_type", None)
        if op_type:
            stmt = stmt.where(LifecycleOperation.operation_type == str(op_type).upper())
        env = filters.pop("environment", None)
        if env:
            stmt = stmt.where(LifecycleOperation.environment_code == str(env).upper())
        date_from = filters.pop("date_from", None)
        if date_from:
            stmt = stmt.where(LifecycleOperation.created_at >= _parse_date(date_from))
        date_to = filters.pop("date_to", None)
        if date_to:
            stmt = stmt.where(LifecycleOperation.created_at < _parse_date(date_to, end=True))
        return super().apply_filters(stmt, filters)

    def by_reference(self, reference: str) -> LifecycleOperation | None:
        return self.session.execute(
            self.base_query().where(LifecycleOperation.reference == reference)
        ).scalar_one_or_none()

    def next_sequence(self) -> int:
        return (self.session.execute(db.select(func.max(LifecycleOperation.id))).scalar() or 0) + 1

    def recent(self, limit: int = 10) -> list[LifecycleOperation]:
        return list(
            self.session.execute(
                self.base_query().order_by(LifecycleOperation.created_at.desc()).limit(limit)
            )
            .scalars()
            .unique()
        )

    def active(self) -> list[LifecycleOperation]:
        return list(
            self.session.execute(
                self.base_query()
                .where(LifecycleOperation.status.in_(["QUEUED", "RUNNING"]))
                .order_by(LifecycleOperation.created_at.desc())
            )
            .scalars()
            .unique()
        )


class AuditRepository(Repository[AuditLog]):
    """Read-only repository: no add/delete exposed for audit records."""

    model = AuditLog
    default_sort = "timestamp"
    sortable = {
        "id": AuditLog.id,
        "timestamp": AuditLog.timestamp,
        "action": AuditLog.action,
        "username": AuditLog.username,
    }
    searchable = [
        AuditLog.action,
        AuditLog.username,
        AuditLog.entity_type,
        AuditLog.entity_id,
        AuditLog.target_name,
        AuditLog.application_code,
        AuditLog.request_id,
    ]

    def apply_filters(self, stmt: Select, filters: dict[str, Any]) -> Select:
        date_from = filters.pop("date_from", None)
        if date_from:
            stmt = stmt.where(AuditLog.timestamp >= _parse_date(date_from))
        date_to = filters.pop("date_to", None)
        if date_to:
            stmt = stmt.where(AuditLog.timestamp < _parse_date(date_to, end=True))
        action = filters.pop("action", None)
        if action:
            stmt = stmt.where(AuditLog.action.ilike(f"{action}%"))
        return super().apply_filters(stmt, filters)

    def add(self, obj, commit: bool = True):  # pragma: no cover - guard
        raise PermissionError("Audit records are written only through AuditRecorder.")

    def delete(self, obj, commit: bool = True) -> None:  # pragma: no cover - guard
        raise PermissionError("Audit records are immutable.")

    def recent(self, limit: int = 10) -> list[AuditLog]:
        return list(
            self.session.execute(
                db.select(AuditLog).order_by(AuditLog.timestamp.desc()).limit(limit)
            ).scalars()
        )

    def iter_filtered(self, **filters):
        stmt = self.apply_filters(db.select(AuditLog), dict(filters))
        stmt = self.apply_search(stmt, filters.get("search"))
        return self.session.execute(stmt.order_by(AuditLog.timestamp.asc())).scalars()


class SecurityEventRepository(Repository[SecurityEvent]):
    model = SecurityEvent
    default_sort = "timestamp"
    sortable = {
        "id": SecurityEvent.id,
        "timestamp": SecurityEvent.timestamp,
        "severity": SecurityEvent.severity,
    }
    searchable = [SecurityEvent.event_type, SecurityEvent.message]

    def unacknowledged(self, limit: int = 20) -> list[SecurityEvent]:
        return list(
            self.session.execute(
                db.select(SecurityEvent)
                .where(SecurityEvent.acknowledged.is_(False))
                .order_by(SecurityEvent.timestamp.desc())
                .limit(limit)
            ).scalars()
        )


class NotificationRepository(Repository[Notification]):
    model = Notification
    default_sort = "created_at"
    sortable = {"id": Notification.id, "created_at": Notification.created_at}

    def for_user(
        self, user_id: int, unread_only: bool = False, limit: int = 50
    ) -> list[Notification]:
        stmt = db.select(Notification).where(
            (Notification.user_id == user_id) | (Notification.user_id.is_(None))
        )
        if unread_only:
            stmt = stmt.where(Notification.read.is_(False))
        return list(
            self.session.execute(
                stmt.order_by(Notification.created_at.desc()).limit(limit)
            ).scalars()
        )

    def unread_count(self, user_id: int) -> int:
        return self.session.execute(
            db.select(func.count(Notification.id)).where(
                (Notification.user_id == user_id) | (Notification.user_id.is_(None)),
                Notification.read.is_(False),
            )
        ).scalar_one()


def _parse_date(value: str, *, end: bool = False) -> datetime:
    from datetime import timedelta

    from app.errors import ValidationError

    try:
        if len(value) == 10:
            parsed = datetime.strptime(value, "%Y-%m-%d")
            return parsed + timedelta(days=1) if end else parsed
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError as exc:
        raise ValidationError("Invalid date filter.", errors={"date": ["Use YYYY-MM-DD."]}) from exc


__all__ = [
    "ApplicationRepository",
    "AuditRepository",
    "DeploymentRepository",
    "EnvironmentRepository",
    "HostGroupRepository",
    "HostRepository",
    "InstanceRepository",
    "NotificationRepository",
    "OperationRepository",
    "PackageRepository",
    "Page",
    "Repository",
    "RoleRepository",
    "SecurityEventRepository",
    "UserRepository",
    "VersionRepository",
]
