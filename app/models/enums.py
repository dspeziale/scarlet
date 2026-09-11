"""Normalized status enumerations shared by models, services and the UI."""

from __future__ import annotations

import enum


class StrEnum(str, enum.Enum):
    def __str__(self) -> str:  # pragma: no cover - trivial
        return str(self.value)

    @classmethod
    def values(cls) -> list[str]:
        return [m.value for m in cls]

    @classmethod
    def parse(cls, value: str | None, default: StrEnum | None = None):
        if value is None:
            return default
        try:
            return cls(str(value).upper())
        except ValueError:
            return default


class EnvironmentType(StrEnum):
    DEV = "DEV"
    PROD = "PROD"


class RuntimeType(StrEnum):
    DOCKER = "DOCKER"
    PODMAN = "PODMAN"
    KUBERNETES = "KUBERNETES"
    NONE = "NONE"


class CredentialType(StrEnum):
    PASSWORD = "PASSWORD"
    PRIVATE_KEY = "PRIVATE_KEY"
    KUBECONFIG = "KUBECONFIG"
    K8S_TOKEN = "K8S_TOKEN"


class HostStatus(StrEnum):
    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"
    UNKNOWN = "UNKNOWN"
    DISABLED = "DISABLED"


class HostKeyStatus(StrEnum):
    UNKNOWN = "UNKNOWN"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    MISMATCH = "MISMATCH"
    REVOKED = "REVOKED"


class ApplicationState(StrEnum):
    RUNNING = "RUNNING"
    STOPPED = "STOPPED"
    STARTING = "STARTING"
    STOPPING = "STOPPING"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"
    NOT_INSTALLED = "NOT_INSTALLED"


class DesiredState(StrEnum):
    RUNNING = "RUNNING"
    STOPPED = "STOPPED"
    ABSENT = "ABSENT"


class HealthStatus(StrEnum):
    HEALTHY = "HEALTHY"
    UNHEALTHY = "UNHEALTHY"
    UNKNOWN = "UNKNOWN"


class HealthCheckType(StrEnum):
    HTTP = "HTTP"
    HTTPS = "HTTPS"
    TCP = "TCP"
    COMMAND = "COMMAND"
    CONTAINER_STATUS = "CONTAINER_STATUS"
    KUBERNETES_STATUS = "KUBERNETES_STATUS"


class PackageStatus(StrEnum):
    UPLOADED = "UPLOADED"
    VALIDATING = "VALIDATING"
    VALID = "VALID"
    INVALID = "INVALID"
    QUARANTINED = "QUARANTINED"


class DeploymentStatus(StrEnum):
    """Fine grained deployment pipeline states."""

    CREATED = "CREATED"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    QUEUED = "QUEUED"
    VALIDATING = "VALIDATING"
    VALIDATED = "VALIDATED"
    PREFLIGHT = "PREFLIGHT"
    TRANSFERRING = "TRANSFERRING"
    TRANSFERRED = "TRANSFERRED"
    INSTALLING = "INSTALLING"
    INSTALLED = "INSTALLED"
    STARTING = "STARTING"
    STARTED = "STARTED"
    HEALTH_CHECKING = "HEALTH_CHECKING"
    SUCCESS = "SUCCESS"
    # failure states
    VALIDATION_FAILED = "VALIDATION_FAILED"
    PREFLIGHT_FAILED = "PREFLIGHT_FAILED"
    TRANSFER_FAILED = "TRANSFER_FAILED"
    INSTALL_FAILED = "INSTALL_FAILED"
    START_FAILED = "START_FAILED"
    HEALTH_CHECK_FAILED = "HEALTH_CHECK_FAILED"
    ROLLBACK_REQUIRED = "ROLLBACK_REQUIRED"
    ROLLING_BACK = "ROLLING_BACK"
    ROLLED_BACK = "ROLLED_BACK"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"

    @property
    def is_terminal(self) -> bool:
        return self in TERMINAL_DEPLOYMENT_STATES

    @property
    def is_failure(self) -> bool:
        return self in FAILED_DEPLOYMENT_STATES

    @property
    def summary(self) -> str:
        """Coarse status (QUEUED/RUNNING/SUCCESS/FAILED/ROLLED_BACK/CANCELLED)."""
        if self in {DeploymentStatus.CREATED, DeploymentStatus.QUEUED, DeploymentStatus.APPROVED}:
            return "QUEUED"
        if self == DeploymentStatus.PENDING_APPROVAL:
            return "PENDING_APPROVAL"
        if self == DeploymentStatus.SUCCESS:
            return "SUCCESS"
        if self == DeploymentStatus.ROLLED_BACK:
            return "ROLLED_BACK"
        if self in {DeploymentStatus.CANCELLED, DeploymentStatus.REJECTED}:
            return "CANCELLED"
        if self in FAILED_DEPLOYMENT_STATES:
            return "FAILED"
        return "RUNNING"


FAILED_DEPLOYMENT_STATES = frozenset(
    {
        DeploymentStatus.VALIDATION_FAILED,
        DeploymentStatus.PREFLIGHT_FAILED,
        DeploymentStatus.TRANSFER_FAILED,
        DeploymentStatus.INSTALL_FAILED,
        DeploymentStatus.START_FAILED,
        DeploymentStatus.HEALTH_CHECK_FAILED,
        DeploymentStatus.ROLLBACK_REQUIRED,
        DeploymentStatus.FAILED,
    }
)

TERMINAL_DEPLOYMENT_STATES = frozenset(
    FAILED_DEPLOYMENT_STATES
    | {
        DeploymentStatus.SUCCESS,
        DeploymentStatus.ROLLED_BACK,
        DeploymentStatus.CANCELLED,
        DeploymentStatus.REJECTED,
    }
)


class DeploymentStrategy(StrEnum):
    SEQUENTIAL = "SEQUENTIAL"
    PARALLEL = "PARALLEL"
    CANARY = "CANARY"


class DeploymentKind(StrEnum):
    DEPLOY = "DEPLOY"
    ROLLBACK = "ROLLBACK"


class StepStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class OperationType(StrEnum):
    START = "START"
    STOP = "STOP"
    RESTART = "RESTART"
    STATUS = "STATUS"
    HEALTH = "HEALTH"
    LOGS = "LOGS"
    VERSION = "VERSION"
    DEPLOY = "DEPLOY"
    ROLLBACK = "ROLLBACK"
    TEST_CONNECTION = "TEST_CONNECTION"
    DISCOVER = "DISCOVER"
    RECONCILE = "RECONCILE"
    SCALE = "SCALE"


class OperationStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    TIMEOUT = "TIMEOUT"

    @property
    def is_terminal(self) -> bool:
        return self in {
            OperationStatus.SUCCESS,
            OperationStatus.FAILED,
            OperationStatus.CANCELLED,
            OperationStatus.TIMEOUT,
        }


class AuditResult(StrEnum):
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    DENIED = "DENIED"
    INFO = "INFO"


class NotificationLevel(StrEnum):
    INFO = "INFO"
    SUCCESS = "SUCCESS"
    WARNING = "WARNING"
    ERROR = "ERROR"


class ConfigValueType(StrEnum):
    CONFIG = "CONFIG"
    SECRET = "SECRET"


class ApprovalStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class SecurityEventSeverity(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class DriftType(StrEnum):
    NONE = "NONE"
    VERSION = "VERSION"
    STATE = "STATE"
    RUNTIME = "RUNTIME"
    CONFIGURATION = "CONFIGURATION"
    MISSING = "MISSING"
    UNEXPECTED_STOP = "UNEXPECTED_STOP"
