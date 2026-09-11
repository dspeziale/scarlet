"""Paramiko based SSH client with strict host key verification and timeouts."""

from __future__ import annotations

import io
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

import paramiko

from app.config.logging import get_logger, redact
from app.errors import (
    RemoteCommandError,
    SSHAuthenticationError,
    SSHConnectionError,
    SSHHostKeyError,
    SSHTimeoutError,
)
from app.ssh.command import RemoteCommand
from app.ssh.host_keys import HostKeyRecord, ScarletHostKeyPolicy, host_entry
from app.ssh.result import CommandResult, truncate_output
from app.utils.time import utcnow

log = get_logger(__name__)


@dataclass
class SSHAuth:
    """Decrypted authentication material. Lives only in memory for the connection."""

    username: str
    password: str | None = None
    private_key: str | None = None
    passphrase: str | None = None

    def load_pkey(self) -> paramiko.PKey | None:
        if not self.private_key:
            return None
        errors: list[str] = []
        for key_cls in (paramiko.Ed25519Key, paramiko.ECDSAKey, paramiko.RSAKey):
            try:
                return key_cls.from_private_key(
                    io.StringIO(self.private_key), password=self.passphrase
                )
            except paramiko.PasswordRequiredException as exc:
                raise SSHAuthenticationError("The private key requires a passphrase.") from exc
            except paramiko.SSHException as exc:
                errors.append(f"{key_cls.__name__}: {exc}")
        raise SSHAuthenticationError(
            "The private key could not be loaded (unsupported format or wrong passphrase).",
            details={"errors": errors},
        )

    def __repr__(self) -> str:  # pragma: no cover
        return f"SSHAuth(username={self.username!r}, password={'***' if self.password else None}, key={'***' if self.private_key else None})"


@dataclass
class SSHConnectionParams:
    hostname: str
    port: int
    auth: SSHAuth
    connect_timeout: int = 30
    command_timeout: int = 600
    host_key: HostKeyRecord | None = None
    host_key_policy: str = "strict"
    on_pending_key: Callable[[HostKeyRecord], None] | None = None
    on_accepted_key: Callable[[HostKeyRecord], None] | None = None
    on_mismatch: Callable[[HostKeyRecord], None] | None = None
    label: str = ""
    extra: dict = field(default_factory=dict)


class RemoteExecutor(Protocol):
    """Interface implemented by the real SSH client and the test fake."""

    def run(self, command: RemoteCommand) -> CommandResult: ...

    def upload(
        self, local_path: str, remote_path: str, progress: Callable[[int, int], None] | None = None
    ) -> int: ...

    def read_file(self, remote_path: str, max_bytes: int = 1024 * 1024) -> str: ...

    def close(self) -> None: ...


class SSHClient:
    """Thin, safe wrapper around ``paramiko.SSHClient``.

    * Never uses AutoAddPolicy.
    * Every command has a timeout.
    * Captures stdout/stderr/exit code/timings.
    * Never logs secrets (auth material is not part of any log line).
    """

    def __init__(self, params: SSHConnectionParams) -> None:
        self.params = params
        self._client: paramiko.SSHClient | None = None
        self._sftp: paramiko.SFTPClient | None = None

    # --- connection ---------------------------------------------------------------
    def connect(self) -> SSHClient:
        params = self.params
        client = paramiko.SSHClient()
        entry = host_entry(params.hostname, params.port)
        if params.host_key is not None:
            client.get_host_keys().add(entry, params.host_key.key_type, params.host_key.to_pkey())
        client.set_missing_host_key_policy(
            ScarletHostKeyPolicy(
                params.host_key_policy,
                on_pending=params.on_pending_key,
                on_accept=params.on_accepted_key,
            )
        )
        pkey = params.auth.load_pkey()
        try:
            client.connect(
                hostname=params.hostname,
                port=params.port,
                username=params.auth.username,
                password=params.auth.password if pkey is None else None,
                pkey=pkey,
                timeout=params.connect_timeout,
                banner_timeout=params.connect_timeout,
                auth_timeout=params.connect_timeout,
                allow_agent=False,
                look_for_keys=False,
            )
        except paramiko.BadHostKeyException as exc:
            presented = HostKeyRecord.from_pkey(exc.key)
            if params.on_mismatch:
                params.on_mismatch(presented)
            client.close()
            raise SSHHostKeyError(
                "HOST KEY MISMATCH: the host presented a key different from the approved one. "
                "Connection blocked. Possible server reinstall or man-in-the-middle attack.",
                details={"presented_fingerprint": presented.fingerprint},
            ) from exc
        except SSHHostKeyError:
            client.close()
            raise
        except paramiko.AuthenticationException as exc:
            client.close()
            raise SSHAuthenticationError(details={"reason": str(exc)}) from exc
        except TimeoutError as exc:
            client.close()
            raise SSHTimeoutError(
                f"Connection to {params.hostname}:{params.port} timed out."
            ) from exc
        except (OSError, paramiko.SSHException) as exc:
            client.close()
            raise SSHConnectionError(
                f"Unable to connect to {params.hostname}:{params.port}: {redact(str(exc))}"
            ) from exc
        transport = client.get_transport()
        if transport is not None:
            transport.set_keepalive(30)
        self._client = client
        return self

    def close(self) -> None:
        if self._sftp is not None:
            try:
                self._sftp.close()
            finally:
                self._sftp = None
        if self._client is not None:
            try:
                self._client.close()
            finally:
                self._client = None

    def __enter__(self) -> SSHClient:
        if self._client is None:
            self.connect()
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    @property
    def connected(self) -> bool:
        transport = self._client.get_transport() if self._client else None
        return bool(transport and transport.is_active())

    # --- execution ----------------------------------------------------------------
    def run(self, command: RemoteCommand) -> CommandResult:
        if self._client is None:
            self.connect()
        assert self._client is not None
        timeout = command.timeout or self.params.command_timeout
        rendered = command.render()
        started = utcnow()
        t0 = time.monotonic()
        log.debug(
            "ssh exec",
            extra={
                "extra_data": {"command": command.rendered_for_log(), "type": command.command_type}
            },
        )
        try:
            transport = self._client.get_transport()
            if transport is None or not transport.is_active():
                raise SSHConnectionError("SSH transport is not active.")
            channel = transport.open_session(timeout=self.params.connect_timeout)
            channel.settimeout(timeout)
            channel.exec_command(rendered)
            if command.stdin is not None:
                channel.sendall(command.stdin.encode())
            channel.shutdown_write()
            stdout_chunks: list[bytes] = []
            stderr_chunks: list[bytes] = []
            timed_out = False
            deadline = t0 + timeout
            while True:
                if channel.recv_ready():
                    stdout_chunks.append(channel.recv(65536))
                if channel.recv_stderr_ready():
                    stderr_chunks.append(channel.recv_stderr(65536))
                if (
                    channel.exit_status_ready()
                    and not channel.recv_ready()
                    and not channel.recv_stderr_ready()
                ):
                    break
                if time.monotonic() > deadline:
                    timed_out = True
                    break
                time.sleep(0.02)
            if timed_out:
                channel.close()
                exit_code = -1
            else:
                exit_code = channel.recv_exit_status()
                # drain
                while channel.recv_ready():
                    stdout_chunks.append(channel.recv(65536))
                while channel.recv_stderr_ready():
                    stderr_chunks.append(channel.recv_stderr(65536))
                channel.close()
        except TimeoutError as exc:
            raise SSHTimeoutError(f"Command timed out after {timeout}s.") from exc
        except paramiko.SSHException as exc:
            raise SSHConnectionError(f"SSH channel error: {redact(str(exc))}") from exc
        completed = utcnow()
        result = CommandResult(
            command=command.rendered_for_log(),
            command_type=command.command_type,
            exit_code=exit_code,
            stdout=truncate_output(b"".join(stdout_chunks).decode("utf-8", "replace")),
            stderr=truncate_output(b"".join(stderr_chunks).decode("utf-8", "replace")),
            started_at=started,
            completed_at=completed,
            duration_seconds=round(time.monotonic() - t0, 3),
            timed_out=timed_out,
        )
        if timed_out:
            raise SSHTimeoutError(
                f"Command '{command.description or command.command_type}' timed out after {timeout}s.",
                details={"result": result.to_dict()},
            )
        if not result.ok and not command.allow_failure:
            raise RemoteCommandError(
                f"{command.description or command.command_type} failed (exit {result.exit_code}).",
                exit_code=result.exit_code,
                stdout=result.stdout,
                stderr=result.stderr,
                details={"command": result.command},
            )
        return result

    # --- SFTP ------------------------------------------------------------------------
    def sftp(self) -> paramiko.SFTPClient:
        if self._client is None:
            self.connect()
        assert self._client is not None
        if self._sftp is None:
            try:
                self._sftp = self._client.open_sftp()
                self._sftp.get_channel().settimeout(self.params.command_timeout)
            except paramiko.SSHException as exc:
                raise SSHConnectionError(
                    f"Unable to open SFTP session: {redact(str(exc))}"
                ) from exc
        return self._sftp

    def upload(
        self, local_path: str, remote_path: str, progress: Callable[[int, int], None] | None = None
    ) -> int:
        from app.ssh.sftp import upload_file

        return upload_file(self, local_path, remote_path, progress=progress)

    def read_file(self, remote_path: str, max_bytes: int = 1024 * 1024) -> str:
        sftp = self.sftp()
        try:
            with sftp.open(remote_path, "rb") as handle:
                data = handle.read(max_bytes)
        except OSError as exc:
            raise RemoteCommandError(f"Unable to read remote file: {exc}") from exc
        return data.decode("utf-8", "replace")
