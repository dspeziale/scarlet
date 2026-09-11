"""Runtime adapter interface.

A ``RuntimeAdapter`` knows how to realise a ``DesiredApplicationState`` on a
specific container runtime and how to observe the ``ActualApplicationState``.
The deployment engine and lifecycle services only talk to this interface; they
never branch on the runtime type.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.deployment.domain import ActualApplicationState, DesiredApplicationState, HealthSpec
from app.deployment.remote_layout import RemoteLayout
from app.models.enums import ApplicationState, DesiredState, HealthStatus, RuntimeType
from app.ssh.client import RemoteExecutor
from app.ssh.result import CommandResult


@dataclass
class HostInfo:
    """Runtime-relevant, already validated facts about the target host."""

    name: str
    runtime_type: str
    base_path: str
    rootless: bool | None = None
    kubernetes_namespace: str | None = None
    kubernetes_context: str | None = None
    kubeconfig: str | None = None  # decrypted kubeconfig content (Kubernetes only, in-memory)
    architecture: str | None = None


@dataclass
class RuntimeContext:
    """Everything an adapter needs to act on one application on one host."""

    executor: RemoteExecutor
    host: HostInfo
    application_code: str
    layout: RemoteLayout
    log: Callable[..., None] = lambda *a, **k: None  # log(level, message, result=None)
    timeout: int = 600

    def run(self, command, *, label: str | None = None) -> CommandResult:
        result = self.executor.run(command)
        self.log("DEBUG", label or command.description or command.command_type, result=result)
        return result


@dataclass
class RuntimeDetection:
    runtime_type: str
    available: bool
    version: str | None = None
    rootless: bool | None = None
    binary_path: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "runtime_type": self.runtime_type,
            "available": self.available,
            "version": self.version,
            "rootless": self.rootless,
            "binary_path": self.binary_path,
            "details": self.details,
        }


@dataclass
class HealthResult:
    status: HealthStatus
    message: str = ""
    attempts: int = 1
    details: dict[str, Any] = field(default_factory=dict)
    duration_seconds: float | None = None

    @property
    def healthy(self) -> bool:
        return self.status == HealthStatus.HEALTHY

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "message": self.message,
            "attempts": self.attempts,
            "details": self.details,
            "duration_seconds": self.duration_seconds,
        }


@dataclass
class LogChunk:
    lines: list[str]
    source: str
    truncated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"lines": self.lines, "source": self.source, "truncated": self.truncated, "count": len(self.lines)}


class RuntimeAdapter(ABC):
    """Abstract runtime adapter. Implementations must be stateless."""

    runtime_type: RuntimeType = RuntimeType.NONE
    supports_scaling = False
    supports_image_load = False

    # --- observation ---------------------------------------------------------------
    @abstractmethod
    def detect(self, ctx: RuntimeContext) -> RuntimeDetection:
        """Detect runtime availability/version. MUST NOT modify the host."""

    @abstractmethod
    def status(self, ctx: RuntimeContext) -> ActualApplicationState:
        """Observe the actual state of the application."""

    @abstractmethod
    def version(self, ctx: RuntimeContext) -> str | None:
        """Return the version currently deployed (from labels/current symlink)."""

    @abstractmethod
    def inspect(self, ctx: RuntimeContext) -> dict[str, Any]:
        """Raw runtime inspection data (sanitized)."""

    @abstractmethod
    def logs(self, ctx: RuntimeContext, lines: int = 200, since: str | None = None) -> LogChunk:
        """Return the last ``lines`` log lines through the runtime's log interface."""

    @abstractmethod
    def health(self, ctx: RuntimeContext, spec: HealthSpec, desired: DesiredApplicationState | None = None) -> HealthResult:
        """Execute a single health probe (retry logic lives in HealthChecker)."""

    # --- mutation ---------------------------------------------------------------------
    @abstractmethod
    def install(self, ctx: RuntimeContext, desired: DesiredApplicationState, release_dir: str) -> dict[str, Any]:
        """Prepare the release on the host (pull/load image, render objects)."""

    @abstractmethod
    def start(self, ctx: RuntimeContext, desired: DesiredApplicationState) -> ActualApplicationState:
        """Start the desired version. Idempotent: running already => ALREADY_RUNNING."""

    @abstractmethod
    def stop(self, ctx: RuntimeContext) -> ActualApplicationState:
        """Stop the application. Idempotent."""

    @abstractmethod
    def remove(self, ctx: RuntimeContext) -> None:
        """Remove runtime objects for the application (not the release files)."""

    def restart(self, ctx: RuntimeContext, desired: DesiredApplicationState) -> ActualApplicationState:
        self.stop(ctx)
        return self.start(ctx, desired)

    def rollback(self, ctx: RuntimeContext, previous: DesiredApplicationState, release_dir: str) -> ActualApplicationState:
        """Activate ``previous`` (stop current, ensure image present, start previous)."""
        self.stop(ctx)
        self.install(ctx, previous, release_dir)
        return self.start(ctx, previous)

    def scale(self, ctx: RuntimeContext, replicas: int) -> ActualApplicationState:
        raise NotImplementedError(f"{self.runtime_type.value} does not support scaling.")

    # --- reconciliation --------------------------------------------------------------------
    def apply(self, ctx: RuntimeContext, desired: DesiredApplicationState) -> ActualApplicationState:
        """Drive the actual state toward ``desired`` (used by remediation)."""
        if desired.state == DesiredState.ABSENT:
            self.remove(ctx)
            return self.status(ctx)
        actual = self.status(ctx)
        if desired.state == DesiredState.STOPPED:
            if actual.state == ApplicationState.RUNNING:
                return self.stop(ctx)
            return actual
        if actual.state != ApplicationState.RUNNING or (actual.version and actual.version != desired.version):
            if actual.state == ApplicationState.RUNNING:
                self.stop(ctx)
            return self.start(ctx, desired)
        return actual
