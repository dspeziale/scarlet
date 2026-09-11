"""Safe remote command construction.

A ``RemoteCommand`` is an argv list, never a shell string. Because SSH ``exec``
necessarily hands the line to the remote login shell, every argument is quoted
with ``shlex.quote`` at render time so no argument can break out of its token.

Additional guarantees:

* the executable (argv[0]) must be in ``ALLOWED_BINARIES``;
* arguments must not contain NUL or newline characters;
* remote paths are validated to live under the SCARLET base directory;
* commands carry metadata (type, description, sensitivity) for auditing.

Business code never builds command lines itself: it uses the builders in this
module or the runtime adapters.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from app.errors import UnsafeCommandError, ValidationError
from app.security.validators import validate_path_segment

ALLOWED_BINARIES: frozenset[str] = frozenset(
    {
        # system inspection (read-only)
        "cat",
        "uname",
        "nproc",
        "free",
        "df",
        "id",
        "hostname",
        "readlink",
        "ls",
        "stat",
        "test",
        "sha256sum",
        "command",
        "which",
        "systemctl",
        "getenforce",
        "timeout",
        "true",
        # filesystem operations within the SCARLET base path
        "mkdir",
        "mv",
        "rm",
        "ln",
        "tar",
        "cp",
        "chmod",
        "find",
        "sh",
        # container runtimes
        "docker",
        "podman",
        "kubectl",
        "helm",
        # health checks
        "curl",
        "nc",
    }
)

# Binaries whose invocation is only allowed through dedicated builders with fixed
# argument shapes (they could otherwise be turned into arbitrary execution).
RESTRICTED_BINARIES = frozenset({"sh", "timeout", "find"})

_FORBIDDEN_CHARS = re.compile(r"[\x00\n\r]")


@dataclass(frozen=True)
class RemoteCommand:
    argv: tuple[str, ...]
    command_type: str
    description: str = ""
    timeout: int | None = None
    sensitive: bool = False
    stdin: str | None = None
    allow_failure: bool = False
    env: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.argv:
            raise UnsafeCommandError("Empty command.")
        binary = PurePosixPath(self.argv[0]).name
        if binary not in ALLOWED_BINARIES:
            raise UnsafeCommandError(
                f"Executable '{binary}' is not in the SCARLET allowlist.",
                details={"binary": binary, "command_type": self.command_type},
            )
        if binary in RESTRICTED_BINARIES and not self.command_type.startswith("builder."):
            raise UnsafeCommandError(
                f"Executable '{binary}' may only be used through trusted builders."
            )
        for arg in self.argv:
            if not isinstance(arg, str):
                raise UnsafeCommandError("Command arguments must be strings.")
            if _FORBIDDEN_CHARS.search(arg):
                raise UnsafeCommandError("Command arguments must not contain NUL or newlines.")
        for key, value in self.env.items():
            if not re.fullmatch(r"[A-Z_][A-Z0-9_]*", key) or _FORBIDDEN_CHARS.search(value):
                raise UnsafeCommandError("Invalid environment variable for remote command.")

    def render(self) -> str:
        """Return the shell-safe command line."""
        parts = [f"{k}={shlex.quote(v)}" for k, v in self.env.items()]
        parts.append(shlex.join(self.argv))
        return " ".join(parts)

    def rendered_for_log(self) -> str:
        if self.sensitive:
            return f"{shlex.quote(self.argv[0])} [arguments redacted]"
        return self.render()

    def with_timeout(self, timeout: int) -> RemoteCommand:
        return RemoteCommand(
            argv=self.argv,
            command_type=self.command_type,
            description=self.description,
            timeout=timeout,
            sensitive=self.sensitive,
            stdin=self.stdin,
            allow_failure=self.allow_failure,
            env=dict(self.env),
        )


# --- remote path safety -------------------------------------------------------


def validate_remote_path(path: str, base: str) -> str:
    """Return ``path`` if it is an absolute, normalized path under ``base``."""
    if not isinstance(path, str) or not path or "\x00" in path or "\n" in path:
        raise UnsafeCommandError("Invalid remote path.")
    candidate = PurePosixPath(path)
    base_path = PurePosixPath(base)
    if not candidate.is_absolute() or not base_path.is_absolute():
        raise UnsafeCommandError("Remote paths must be absolute.")
    if ".." in candidate.parts or "." in candidate.parts[1:]:
        raise UnsafeCommandError("Remote paths must be normalized (no '.' or '..').")
    if candidate != base_path and base_path not in candidate.parents:
        raise UnsafeCommandError(
            "Remote path escapes the SCARLET base directory.",
            details={"path": str(candidate), "base": str(base_path)},
        )
    for part in candidate.parts[1:]:
        validate_path_segment(part, field="remote_path")
    return str(candidate)


def join_remote(base: str, *segments: str) -> str:
    """Join validated segments under ``base``."""
    path = PurePosixPath(base)
    for segment in segments:
        path = path / validate_path_segment(segment, field="remote_path")
    return validate_remote_path(str(path), base)


# --- trusted builders -----------------------------------------------------------


class SystemCommands:
    """Read-only host inspection commands (used by discovery/preflight)."""

    @staticmethod
    def os_release() -> RemoteCommand:
        return RemoteCommand(("cat", "/etc/os-release"), "system.os_release", "Read OS release")

    @staticmethod
    def uname() -> RemoteCommand:
        return RemoteCommand(("uname", "-srm"), "system.uname", "Kernel and architecture")

    @staticmethod
    def nproc() -> RemoteCommand:
        return RemoteCommand(("nproc",), "system.nproc", "CPU count")

    @staticmethod
    def memory() -> RemoteCommand:
        return RemoteCommand(("free", "-m"), "system.memory", "Memory usage")

    @staticmethod
    def disk(path: str = "/") -> RemoteCommand:
        if path != "/":
            path = validate_remote_path(path, "/opt") if path.startswith("/opt") else "/"
        return RemoteCommand(("df", "-Pm", path), "system.disk", "Disk usage")

    @staticmethod
    def whoami() -> RemoteCommand:
        return RemoteCommand(("id", "-un"), "system.whoami", "Remote user")

    @staticmethod
    def uid() -> RemoteCommand:
        return RemoteCommand(("id", "-u"), "system.uid", "Remote uid")

    @staticmethod
    def hostname() -> RemoteCommand:
        return RemoteCommand(("hostname", "-f"), "system.hostname", "FQDN", allow_failure=True)

    @staticmethod
    def selinux() -> RemoteCommand:
        return RemoteCommand(("getenforce",), "system.selinux", "SELinux mode", allow_failure=True)

    @staticmethod
    def which(binary: str) -> RemoteCommand:
        if binary not in {"docker", "podman", "kubectl", "helm", "curl", "nc", "tar", "sha256sum"}:
            raise UnsafeCommandError("Lookup of this binary is not allowed.")
        return RemoteCommand(
            ("command", "-v", binary), f"system.which.{binary}", f"Locate {binary}", allow_failure=True
        )

    @staticmethod
    def runtime_version(binary: str) -> RemoteCommand:
        if binary not in {"docker", "podman"}:
            raise UnsafeCommandError("Unsupported runtime binary.")
        return RemoteCommand(
            (binary, "version", "--format", "{{.Client.Version}}"),
            f"runtime.version.{binary}",
            f"{binary} version",
            allow_failure=True,
        )

    @staticmethod
    def podman_info_rootless() -> RemoteCommand:
        return RemoteCommand(
            ("podman", "info", "--format", "{{.Host.Security.Rootless}}"),
            "runtime.podman.rootless",
            "Podman rootless mode",
            allow_failure=True,
        )

    @staticmethod
    def kubectl_version() -> RemoteCommand:
        return RemoteCommand(
            ("kubectl", "version", "--output=json"),
            "runtime.kubectl.version",
            "kubectl/cluster version",
            allow_failure=True,
            timeout=30,
        )


class FileCommands:
    """Filesystem operations restricted to paths under the SCARLET base directory."""

    def __init__(self, base_path: str) -> None:
        self.base = validate_remote_path(base_path, base_path)

    def _p(self, path: str) -> str:
        return validate_remote_path(path, self.base)

    def mkdir(self, path: str) -> RemoteCommand:
        return RemoteCommand(("mkdir", "-p", self._p(path)), "fs.mkdir", "Create directory")

    def exists(self, path: str) -> RemoteCommand:
        return RemoteCommand(("test", "-e", self._p(path)), "fs.exists", "Check path", allow_failure=True)

    def is_dir(self, path: str) -> RemoteCommand:
        return RemoteCommand(("test", "-d", self._p(path)), "fs.isdir", "Check directory", allow_failure=True)

    def remove_tree(self, path: str) -> RemoteCommand:
        target = self._p(path)
        if PurePosixPath(target) == PurePosixPath(self.base) or len(PurePosixPath(target).parts) < 4:
            raise UnsafeCommandError("Refusing to remove a top-level SCARLET directory.")
        return RemoteCommand(("rm", "-rf", "--", target), "fs.rmtree", "Remove directory")

    def remove_file(self, path: str) -> RemoteCommand:
        return RemoteCommand(("rm", "-f", "--", self._p(path)), "fs.rm", "Remove file")

    def move(self, src: str, dst: str) -> RemoteCommand:
        return RemoteCommand(("mv", "-T", "--", self._p(src), self._p(dst)), "fs.mv", "Move")

    def symlink(self, target: str, link_path: str) -> RemoteCommand:
        return RemoteCommand(
            ("ln", "-sfn", "--", self._p(target), self._p(link_path)), "fs.symlink", "Create symlink"
        )

    def atomic_symlink_switch(self, target: str, link_path: str) -> list[RemoteCommand]:
        """Create ``link_path`` -> ``target`` atomically via temp link + rename."""
        tmp_link = f"{self._p(link_path)}.tmp"
        return [
            RemoteCommand(("ln", "-sfn", "--", self._p(target), tmp_link), "fs.symlink", "Prepare symlink"),
            RemoteCommand(("mv", "-T", "--", tmp_link, self._p(link_path)), "fs.mv", "Activate symlink"),
        ]

    def readlink(self, link_path: str) -> RemoteCommand:
        return RemoteCommand(
            ("readlink", "-f", "--", self._p(link_path)), "fs.readlink", "Resolve symlink", allow_failure=True
        )

    def list_dir(self, path: str) -> RemoteCommand:
        return RemoteCommand(("ls", "-1", "--", self._p(path)), "fs.ls", "List directory", allow_failure=True)

    def sha256(self, path: str) -> RemoteCommand:
        return RemoteCommand(("sha256sum", "--", self._p(path)), "fs.sha256", "Checksum")

    def extract_tar(self, archive: str, destination: str) -> RemoteCommand:
        return RemoteCommand(
            (
                "tar",
                "--no-same-owner",
                "--no-same-permissions",
                "--no-overwrite-dir",
                "-xzf",
                self._p(archive),
                "-C",
                self._p(destination),
            ),
            "fs.tar_extract",
            "Extract release package",
        )

    def cat(self, path: str) -> RemoteCommand:
        return RemoteCommand(("cat", "--", self._p(path)), "fs.cat", "Read file", allow_failure=True)

    def chmod_exec(self, path: str) -> RemoteCommand:
        return RemoteCommand(("chmod", "u+x", "--", self._p(path)), "fs.chmod", "Make executable")

    def run_hook(self, script_path: str, release_dir: str, timeout: int, env: dict[str, str]) -> RemoteCommand:
        """Execute a package hook script with ``sh`` inside the release directory.

        Hooks are only run for applications with ``allow_hooks`` and the script
        path is validated to be inside ``release_dir/scripts``.
        """
        script = self._p(script_path)
        release = self._p(release_dir)
        scripts_dir = PurePosixPath(release) / "scripts"
        if scripts_dir not in PurePosixPath(script).parents:
            raise UnsafeCommandError("Hook scripts must live inside the release 'scripts/' directory.")
        if not script.endswith(".sh"):
            raise UnsafeCommandError("Hook scripts must be .sh files.")
        if timeout < 1 or timeout > 3600:
            raise UnsafeCommandError("Hook timeout must be between 1 and 3600 seconds.")
        safe_env = {}
        for key, value in env.items():
            if not re.fullmatch(r"SCARLET_[A-Z0-9_]+", key):
                raise UnsafeCommandError("Hook environment keys must start with SCARLET_.")
            safe_env[key] = value
        return RemoteCommand(
            ("timeout", str(timeout), "sh", "-e", script),
            "builder.hook",
            f"Run hook {PurePosixPath(script).name}",
            timeout=timeout + 5,
            env=safe_env,
        )

    def find_old_dirs(self, path: str, days: int) -> RemoteCommand:
        if days < 1:
            raise ValidationError("days must be >= 1")
        return RemoteCommand(
            ("find", self._p(path), "-mindepth", "1", "-maxdepth", "1", "-type", "d", "-mtime", f"+{int(days)}"),
            "builder.find_old",
            "List stale directories",
            allow_failure=True,
        )
