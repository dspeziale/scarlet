"""Runtime adapters: Docker, Podman, Kubernetes behind one interface."""

from app.runtimes.base import (
    HealthResult,
    HostInfo,
    LogChunk,
    RuntimeAdapter,
    RuntimeContext,
    RuntimeDetection,
)
from app.runtimes.container import DockerRuntimeAdapter, PodmanRuntimeAdapter
from app.runtimes.factory import RuntimeFactory
from app.runtimes.kubernetes import KubernetesRuntimeAdapter

__all__ = [
    "DockerRuntimeAdapter",
    "HealthResult",
    "HostInfo",
    "KubernetesRuntimeAdapter",
    "LogChunk",
    "PodmanRuntimeAdapter",
    "RuntimeAdapter",
    "RuntimeContext",
    "RuntimeDetection",
    "RuntimeFactory",
]
