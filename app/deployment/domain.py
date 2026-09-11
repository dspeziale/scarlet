"""Control-plane domain objects.

SCARLET is a control plane: operators express a DESIRED state for an
application on a target, the reconciler observes the ACTUAL state, and the
deployment engine executes a DEPLOYMENT PLAN that drives actual toward desired.

These objects are runtime-agnostic. Runtime adapters translate them into
Docker / Podman / Kubernetes operations.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from app.models.enums import ApplicationState, DesiredState, DriftType, HealthStatus, StepStatus
from app.utils.time import duration_seconds, utcnow


@dataclass(frozen=True)
class HealthSpec:
    check_type: str = "CONTAINER_STATUS"  # HTTP|HTTPS|TCP|COMMAND|CONTAINER_STATUS|KUBERNETES_STATUS
    path: str = "/health"
    port: int | None = None
    expected_status: int = 200
    timeout: int = 10
    retries: int = 5
    interval: int = 3
    command: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DesiredApplicationState:
    """What the operator wants running on a target."""

    application_code: str
    version: str
    state: DesiredState = DesiredState.RUNNING
    replicas: int = 1
    image: str | None = None  # name:tag
    manifest: dict[str, Any] = field(default_factory=dict)
    environment: dict[str, str] = field(default_factory=dict)  # config + decrypted secrets
    health: HealthSpec = field(default_factory=HealthSpec)
    ports: tuple[str, ...] = ()  # "host:container" strings validated upstream
    volumes: tuple[str, ...] = ()
    resources: dict[str, str] = field(default_factory=dict)
    namespace: str | None = None

    @property
    def container_name(self) -> str:
        return self.application_code

    def to_dict(self, *, redact_env: bool = True) -> dict[str, Any]:
        data = {
            "application_code": self.application_code,
            "version": self.version,
            "state": self.state.value,
            "replicas": self.replicas,
            "image": self.image,
            "ports": list(self.ports),
            "volumes": list(self.volumes),
            "resources": dict(self.resources),
            "namespace": self.namespace,
            "health": self.health.to_dict(),
            "environment_keys": sorted(self.environment.keys()),
        }
        if not redact_env:
            data["environment"] = dict(self.environment)
        return data


@dataclass
class ActualApplicationState:
    """What was observed on the target."""

    application_code: str
    version: str | None = None
    state: ApplicationState = ApplicationState.UNKNOWN
    replicas: int | None = None
    runtime: str | None = None
    image: str | None = None
    health: HealthStatus = HealthStatus.UNKNOWN
    observed_at: datetime = field(default_factory=utcnow)
    details: dict[str, Any] = field(default_factory=dict)
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "application_code": self.application_code,
            "version": self.version,
            "state": self.state.value,
            "replicas": self.replicas,
            "runtime": self.runtime,
            "image": self.image,
            "health": self.health.value,
            "observed_at": self.observed_at.isoformat(),
            "details": self.details,
            "message": self.message,
        }


@dataclass
class DriftReport:
    detected: bool
    drift_type: DriftType
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"detected": self.detected, "drift_type": self.drift_type.value, "details": self.details}


def compute_drift(desired: DesiredApplicationState | None, actual: ActualApplicationState) -> DriftReport:
    """Compare desired and actual state and classify the difference."""
    if desired is None:
        return DriftReport(False, DriftType.NONE)
    details: dict[str, Any] = {
        "desired_version": desired.version,
        "actual_version": actual.version,
        "desired_state": desired.state.value,
        "actual_state": actual.state.value,
    }
    if desired.state == DesiredState.ABSENT:
        if actual.state in {ApplicationState.NOT_INSTALLED, ApplicationState.UNKNOWN}:
            return DriftReport(False, DriftType.NONE, details)
        return DriftReport(True, DriftType.STATE, details)
    if actual.state == ApplicationState.NOT_INSTALLED:
        return DriftReport(True, DriftType.MISSING, details)
    if actual.state == ApplicationState.UNKNOWN:
        return DriftReport(False, DriftType.NONE, details)  # cannot judge; not drift
    if actual.version and actual.version != desired.version:
        return DriftReport(True, DriftType.VERSION, details)
    if desired.state == DesiredState.RUNNING and actual.state in {ApplicationState.STOPPED, ApplicationState.FAILED}:
        return DriftReport(True, DriftType.UNEXPECTED_STOP, details)
    if desired.state == DesiredState.STOPPED and actual.state == ApplicationState.RUNNING:
        return DriftReport(True, DriftType.STATE, details)
    if desired.replicas and actual.replicas is not None and actual.replicas != desired.replicas:
        details["desired_replicas"] = desired.replicas
        details["actual_replicas"] = actual.replicas
        return DriftReport(True, DriftType.STATE, details)
    return DriftReport(False, DriftType.NONE, details)


# --- planning -------------------------------------------------------------------


@dataclass(frozen=True)
class PlanStep:
    name: str  # machine name, e.g. "transfer"
    label: str  # human label, e.g. "Transfer package"
    kind: str  # validate|preflight|transfer|install|hook|activate|start|health|finalize|rollback|cleanup
    params: dict[str, Any] = field(default_factory=dict)
    critical: bool = True  # failure aborts the plan
    rollback_trigger: bool = False  # failure after this step makes rollback meaningful

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "kind": self.kind,
            "params": self.params,
            "critical": self.critical,
            "rollback_trigger": self.rollback_trigger,
        }


@dataclass
class DeploymentPlan:
    """Ordered steps that move a target from its current release to the desired one."""

    reference: str
    application_code: str
    target_name: str
    runtime_type: str
    desired: DesiredApplicationState
    previous_version: str | None
    steps: list[PlanStep]
    strategy: str = "RECREATE"
    auto_rollback: bool = False
    created_at: datetime = field(default_factory=utcnow)

    def to_dict(self) -> dict[str, Any]:
        return {
            "reference": self.reference,
            "application_code": self.application_code,
            "target_name": self.target_name,
            "runtime_type": self.runtime_type,
            "previous_version": self.previous_version,
            "strategy": self.strategy,
            "auto_rollback": self.auto_rollback,
            "desired": self.desired.to_dict(),
            "steps": [s.to_dict() for s in self.steps],
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class StepExecution:
    step: PlanStep
    status: StepStatus = StepStatus.PENDING
    started_at: datetime | None = None
    completed_at: datetime | None = None
    stdout: str = ""
    stderr: str = ""
    exit_code: int | None = None
    error_message: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def duration_seconds(self) -> float | None:
        return duration_seconds(self.started_at, self.completed_at)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.step.name,
            "label": self.step.label,
            "status": self.status.value,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "duration_seconds": self.duration_seconds,
            "exit_code": self.exit_code,
            "error_message": self.error_message,
            "details": self.details,
        }


@dataclass
class DeploymentExecution:
    """Runtime record of executing a plan."""

    plan: DeploymentPlan
    steps: list[StepExecution]
    status: str = "RUNNING"
    started_at: datetime = field(default_factory=utcnow)
    completed_at: datetime | None = None
    error_code: str | None = None
    error_message: str | None = None
    actual: ActualApplicationState | None = None
    rolled_back: bool = False

    @property
    def succeeded(self) -> bool:
        return self.status == "SUCCESS"

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "duration_seconds": duration_seconds(self.started_at, self.completed_at),
            "error_code": self.error_code,
            "error_message": self.error_message,
            "rolled_back": self.rolled_back,
            "actual": self.actual.to_dict() if self.actual else None,
            "steps": [s.to_dict() for s in self.steps],
        }
