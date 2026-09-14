"""Stand-in executor for targets that have no shell.

A Kubernetes target reached through the cluster API is not a machine SCARLET can log into.
The adapters for that mode never execute a command, so this executor exists to satisfy the
:class:`~app.ssh.client.RemoteExecutor` interface and to fail loudly, with an explanation,
if some code path still assumes a shell is available.
"""

from __future__ import annotations

from collections.abc import Callable

from app.errors import RuntimeOperationError
from app.ssh.command import RemoteCommand
from app.ssh.result import CommandResult

MESSAGE = (
    "Target '{name}' is managed through the Kubernetes API: it has no SSH shell. "
    "This operation needs a command on a host, which does not apply to a cluster target."
)


class ClusterExecutor:
    """Implements the executor interface without ever running anything."""

    def __init__(self, host_name: str) -> None:
        self.host_name = host_name
        self.closed = False

    def _refuse(self, what: str) -> RuntimeOperationError:
        return RuntimeOperationError(
            MESSAGE.format(name=self.host_name),
            details={"operation": what, "host": self.host_name, "access_mode": "API"},
        )

    def run(self, command: RemoteCommand) -> CommandResult:
        raise self._refuse(command.command_type)

    def upload(
        self,
        local_path: str,
        remote_path: str,
        progress: Callable[[int, int], None] | None = None,
    ) -> int:
        raise self._refuse("upload")

    def read_file(self, remote_path: str, max_bytes: int = 1024 * 1024) -> str:
        raise self._refuse("read_file")

    def close(self) -> None:
        self.closed = True

    def __enter__(self) -> ClusterExecutor:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
