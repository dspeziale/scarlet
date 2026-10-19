"""Kubernetes provider interface. Implemented by the live client and by the demo store."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from typing import Any

from .kinds import KindInfo


class LogStream(ABC):
    """Iterator of log lines that can be closed from another thread."""

    @abstractmethod
    def __iter__(self) -> Iterator[str]: ...

    @abstractmethod
    def close(self) -> None: ...


class KubernetesProvider(ABC):
    demo: bool = False

    @abstractmethod
    def info(self) -> dict[str, Any]:
        """{connected, context, server, version{gitVersion, major, minor, platform}, error?}"""

    @abstractmethod
    def list(
        self,
        kind: KindInfo,
        namespace: str | None = None,
        *,
        label_selector: str | None = None,
        field_selector: str | None = None,
    ) -> list[dict[str, Any]]: ...

    @abstractmethod
    def get(self, kind: KindInfo, name: str, namespace: str | None = None) -> dict[str, Any]: ...

    @abstractmethod
    def apply(self, manifest: dict[str, Any], *, dry_run: bool = False, force: bool = False) -> dict[str, Any]:
        """Server-side apply (create or update)."""

    @abstractmethod
    def create(self, manifest: dict[str, Any], *, dry_run: bool = False) -> dict[str, Any]: ...

    @abstractmethod
    def patch(
        self,
        kind: KindInfo,
        name: str,
        namespace: str | None,
        body: Any,
        *,
        patch_type: str = "merge",
        dry_run: bool = False,
    ) -> dict[str, Any]: ...

    @abstractmethod
    def delete(
        self, kind: KindInfo, name: str, namespace: str | None, *, propagation: str = "Background"
    ) -> dict[str, Any]: ...

    @abstractmethod
    def pod_logs(
        self,
        name: str,
        namespace: str,
        *,
        container: str | None = None,
        tail_lines: int | None = None,
        since_seconds: int | None = None,
        timestamps: bool = False,
        previous: bool = False,
        limit_bytes: int | None = None,
    ) -> str: ...

    @abstractmethod
    def stream_pod_logs(
        self,
        name: str,
        namespace: str,
        *,
        container: str | None = None,
        tail_lines: int | None = None,
        since_time: str | None = None,
    ) -> LogStream:
        """Follow logs; every line is prefixed with an RFC3339 timestamp and a space."""

    @abstractmethod
    def evict(self, name: str, namespace: str) -> None: ...

    @abstractmethod
    def node_metrics(self) -> list[dict[str, Any]] | None:
        """metrics.k8s.io NodeMetrics items, or None when metrics-server is not available."""

    @abstractmethod
    def pod_metrics(self, namespace: str | None = None) -> list[dict[str, Any]] | None: ...

    def close(self) -> None:  # noqa: B027 - optional hook
        pass
