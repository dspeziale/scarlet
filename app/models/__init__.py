"""SQLAlchemy models. Import this module to register every mapped class."""

from app.models.application import Application, ApplicationInstance, ApplicationVersion, Package
from app.models.audit import AuditLog, SecurityEvent
from app.models.base import Base
from app.models.configuration import Configuration, ConfigurationEntry, ConfigurationVersion
from app.models.deployment import Deployment, DeploymentApproval, DeploymentBatch, DeploymentStep
from app.models.host import (
    Environment,
    HostGroup,
    HostGroupMember,
    RuntimeCapability,
    SSHKey,
    TargetCredential,
    TargetHost,
)
from app.models.lifecycle import DistributedLock, HealthCheck, LifecycleOperation, OperationLog
from app.models.notification import Notification
from app.models.system import SystemSetting
from app.models.user import ApiToken, Permission, Role, RolePermission, User, UserRole

__all__ = [
    "ApiToken",
    "Application",
    "ApplicationInstance",
    "ApplicationVersion",
    "AuditLog",
    "Base",
    "Configuration",
    "ConfigurationEntry",
    "ConfigurationVersion",
    "Deployment",
    "DeploymentApproval",
    "DeploymentBatch",
    "DeploymentStep",
    "DistributedLock",
    "Environment",
    "HealthCheck",
    "HostGroup",
    "HostGroupMember",
    "LifecycleOperation",
    "Notification",
    "OperationLog",
    "Package",
    "Permission",
    "Role",
    "RolePermission",
    "RuntimeCapability",
    "SSHKey",
    "SecurityEvent",
    "SystemSetting",
    "TargetCredential",
    "TargetHost",
    "User",
    "UserRole",
]
