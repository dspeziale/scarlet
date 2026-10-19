"""Role based access control. Enforced in the backend on every endpoint."""

from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    ADMIN = "admin"
    OPERATOR = "operator"
    VIEWER = "viewer"


class Perm(StrEnum):
    CLUSTER_READ = "cluster.read"
    SECRETS_READ_VALUES = "secrets.read_values"
    LOGS_READ = "logs.read"
    WORKLOADS_DEPLOY = "workloads.deploy"
    WORKLOADS_SCALE = "workloads.scale"
    WORKLOADS_RESTART = "workloads.restart"
    WORKLOADS_ROLLOUT = "workloads.rollout"
    PODS_DELETE = "pods.delete"
    RESOURCES_APPLY = "resources.apply"
    RESOURCES_DELETE = "resources.delete"
    NODES_MAINTAIN = "nodes.maintain"
    PODMAN_READ = "podman.read"
    PODMAN_OPERATE = "podman.operate"
    PODMAN_MANAGE = "podman.manage"
    MONITORING_READ = "monitoring.read"
    NOTIFICATIONS_ACK = "notifications.ack"
    AUDIT_READ = "audit.read"
    USERS_MANAGE = "users.manage"
    SETTINGS_READ = "settings.read"
    SETTINGS_MANAGE = "settings.manage"
    BACKUP_READ = "backup.read"
    BACKUP_MANAGE = "backup.manage"
    MAINTENANCE = "maintenance.run"


_VIEWER = {
    Perm.CLUSTER_READ,
    Perm.PODMAN_READ,
    Perm.MONITORING_READ,
}

_OPERATOR = _VIEWER | {
    Perm.LOGS_READ,
    Perm.WORKLOADS_DEPLOY,
    Perm.WORKLOADS_SCALE,
    Perm.WORKLOADS_RESTART,
    Perm.WORKLOADS_ROLLOUT,
    Perm.PODS_DELETE,
    Perm.PODMAN_OPERATE,
    Perm.NOTIFICATIONS_ACK,
    Perm.BACKUP_READ,
    Perm.SETTINGS_READ,
}

ROLE_PERMISSIONS: dict[Role, frozenset[Perm]] = {
    Role.VIEWER: frozenset(_VIEWER),
    Role.OPERATOR: frozenset(_OPERATOR),
    Role.ADMIN: frozenset(Perm),
}


def has_perm(role: str, perm: Perm) -> bool:
    try:
        return perm in ROLE_PERMISSIONS[Role(role)]
    except ValueError:
        return False


def permissions_for(role: str) -> list[str]:
    try:
        return sorted(p.value for p in ROLE_PERMISSIONS[Role(role)])
    except ValueError:
        return []
