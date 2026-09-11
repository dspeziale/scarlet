"""Runtime adapter registry.

New runtimes are added by registering an adapter class here; the deployment
engine and lifecycle service never need to change.
"""

from __future__ import annotations

from app.errors import RuntimeNotSupportedError
from app.models.enums import RuntimeType
from app.runtimes.base import RuntimeAdapter
from app.runtimes.container import DockerRuntimeAdapter, PodmanRuntimeAdapter
from app.runtimes.kubernetes import KubernetesRuntimeAdapter


class RuntimeFactory:
    _registry: dict[str, type[RuntimeAdapter]] = {}

    @classmethod
    def register(cls, adapter_cls: type[RuntimeAdapter]) -> type[RuntimeAdapter]:
        cls._registry[adapter_cls.runtime_type.value] = adapter_cls
        return adapter_cls

    @classmethod
    def get(cls, runtime_type: str | RuntimeType) -> RuntimeAdapter:
        key = (
            runtime_type.value
            if isinstance(runtime_type, RuntimeType)
            else str(runtime_type).upper()
        )
        adapter_cls = cls._registry.get(key)
        if adapter_cls is None:
            raise RuntimeNotSupportedError(
                f"No runtime adapter is registered for '{key}'.", details={"runtime_type": key}
            )
        return adapter_cls()

    @classmethod
    def supported(cls) -> list[str]:
        return sorted(cls._registry)

    @classmethod
    def detectable(cls) -> list[RuntimeAdapter]:
        return [c() for c in cls._registry.values()]


RuntimeFactory.register(DockerRuntimeAdapter)
RuntimeFactory.register(PodmanRuntimeAdapter)
RuntimeFactory.register(KubernetesRuntimeAdapter)
