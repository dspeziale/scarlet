"""One way to open a target, whatever kind of target it is.

Most targets are Linux hosts reached over SSH. A Kubernetes target registered with a
kubeconfig has no shell at all: SCARLET talks to the cluster API and there is nothing to
connect to over SSH. Services must not branch on that themselves, so they all call
``open_target`` and receive an executor plus the :class:`HostInfo` the adapters expect.

The decrypted kubeconfig lives in memory for the duration of the block and is wiped on the
way out, exactly like an SSH session is closed.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING

from flask import current_app

from app.models.enums import RuntimeType
from app.runtimes.base import HostInfo
from app.security.crypto import get_cipher
from app.ssh.cluster import ClusterExecutor
from app.ssh.factory import get_ssh_factory

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.models.host import TargetHost
    from app.ssh.client import RemoteExecutor


def base_path_for(host: TargetHost) -> str:
    return host.remote_base_path or current_app.config["SCARLET_REMOTE_BASE_PATH"]


def build_host_info(host: TargetHost, *, with_credentials: bool = True) -> HostInfo:
    """Runtime-relevant facts about a target, with the kubeconfig decrypted when needed."""
    info = HostInfo(
        name=host.name,
        runtime_type=host.runtime_type,
        base_path=base_path_for(host),
        rootless=host.runtime_rootless,
        kubernetes_namespace=host.kubernetes_namespace,
        kubernetes_context=host.kubernetes_context,
        architecture=host.architecture,
    )
    if (
        with_credentials
        and host.runtime_type == RuntimeType.KUBERNETES.value
        and host.kubernetes_credential is not None
    ):
        info.kubeconfig = get_cipher().decrypt(host.kubernetes_credential.encrypted_secret)
    return info


def open_executor(host: TargetHost, **kwargs: int) -> RemoteExecutor:
    """The executor for a target, without the context manager.

    For long flows (a deployment) the caller already owns a try/finally and closes it there.
    """
    if host.is_cluster_managed:
        return ClusterExecutor(host.name)
    return get_ssh_factory().connect(host, **kwargs)


@contextmanager
def open_target(
    host: TargetHost,
    *,
    connect_timeout: int | None = None,
    command_timeout: int | None = None,
) -> Iterator[tuple[RemoteExecutor, HostInfo]]:
    """Yield ``(executor, host_info)`` for a target, SSH or cluster.

    For a cluster target the executor refuses every command: reaching it would mean a code
    path still assumes a shell, and failing loudly is better than half-working.
    """
    info = build_host_info(host)
    if host.is_cluster_managed:
        executor: RemoteExecutor = ClusterExecutor(host.name)
        try:
            yield executor, info
        finally:
            executor.close()
            info.kubeconfig = None
        return

    kwargs: dict[str, int] = {}
    if connect_timeout is not None:
        kwargs["connect_timeout"] = connect_timeout
    if command_timeout is not None:
        kwargs["command_timeout"] = command_timeout
    client = get_ssh_factory().connect(host, **kwargs)
    try:
        yield client, info
    finally:
        try:
            client.close()
        except Exception:  # noqa: BLE001 - closing must never mask the real error
            pass
        info.kubeconfig = None
