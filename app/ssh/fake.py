"""In-memory fake of the SSH layer used by tests and the local demo mode.

``FakeSSHClient`` simulates an Oracle Linux host with Podman (or Docker)
installed. It understands the exact command shapes produced by SCARLET's
trusted builders and runtime adapters, keeps a tiny virtual filesystem and a
container table, and records every command for assertions.
"""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from app.errors import RemoteCommandError, SSHConnectionError
from app.ssh.command import RemoteCommand
from app.ssh.result import CommandResult
from app.utils.time import utcnow


@dataclass
class FakeContainer:
    name: str
    image: str
    status: str = "running"  # running | exited | created
    labels: dict[str, str] = field(default_factory=dict)
    ports: list[str] = field(default_factory=list)
    logs: list[str] = field(default_factory=list)
    exit_code: int = 0


@dataclass
class FakeHostState:
    """Shared mutable state of a simulated host (survives client reconnects)."""

    runtime: str = "podman"  # podman | docker | none
    runtime_version: str = "4.9.4"
    rootless: bool = True
    os_release: str = 'NAME="Oracle Linux Server"\nVERSION="9.4"\nID="ol"\nVERSION_ID="9.4"\nPRETTY_NAME="Oracle Linux Server 9.4"\n'
    kernel: str = "Linux 5.15.0-206.153.7.1.el9uek.x86_64 x86_64"
    nproc: int = 4
    mem_total_mb: int = 7821
    mem_available_mb: int = 5210
    disk_total_mb: int = 102400
    disk_available_mb: int = 61440
    kubectl: bool = False
    dirs: set[str] = field(default_factory=set)
    files: dict[str, bytes] = field(default_factory=dict)
    symlinks: dict[str, str] = field(default_factory=dict)
    containers: dict[str, FakeContainer] = field(default_factory=dict)
    images: set[str] = field(default_factory=set)
    commands: list[str] = field(default_factory=list)
    fail_on: dict[str, tuple[int, str]] = field(default_factory=dict)  # command_type -> (exit, stderr)
    health_http_status: int = 200
    unreachable: bool = False
    hook_log: list[str] = field(default_factory=list)

    def reset(self) -> None:
        self.dirs.clear()
        self.files.clear()
        self.symlinks.clear()
        self.containers.clear()
        self.images.clear()
        self.commands.clear()
        self.fail_on.clear()
        self.hook_log.clear()


class FakeSSHClient:
    """Implements the ``RemoteExecutor`` protocol against ``FakeHostState``."""

    def __init__(self, state: FakeHostState, label: str = "fake") -> None:
        self.state = state
        self.label = label
        self.closed = False
        if state.unreachable:
            raise SSHConnectionError(f"Simulated host {label} is unreachable.")

    # --- protocol -----------------------------------------------------------------
    def close(self) -> None:
        self.closed = True

    def __enter__(self) -> FakeSSHClient:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def upload(self, local_path: str, remote_path: str, progress: Callable[[int, int], None] | None = None) -> int:
        with open(local_path, "rb") as fh:
            data = fh.read()
        parent = str(PurePosixPath(remote_path).parent)
        if parent not in self.state.dirs:
            raise RemoteCommandError(f"Remote directory {parent} does not exist.")
        self.state.files[remote_path] = data
        if progress:
            progress(len(data), len(data))
        return len(data)

    def read_file(self, remote_path: str, max_bytes: int = 1024 * 1024) -> str:
        data = self.state.files.get(remote_path)
        if data is None:
            raise RemoteCommandError(f"No such file: {remote_path}")
        return data[:max_bytes].decode("utf-8", "replace")

    def run(self, command: RemoteCommand) -> CommandResult:
        rendered = command.render()
        self.state.commands.append(rendered)
        started = utcnow()
        t0 = time.monotonic()
        if command.command_type in self.state.fail_on:
            exit_code, stderr = self.state.fail_on[command.command_type]
            stdout = ""
        else:
            exit_code, stdout, stderr = self._dispatch(list(command.argv), command)
        result = CommandResult(
            command=command.rendered_for_log(),
            command_type=command.command_type,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            started_at=started,
            completed_at=utcnow(),
            duration_seconds=round(time.monotonic() - t0, 4),
        )
        if not result.ok and not command.allow_failure:
            raise RemoteCommandError(
                f"{command.description or command.command_type} failed (exit {exit_code}).",
                exit_code=exit_code,
                stdout=stdout,
                stderr=stderr,
                details={"command": result.command},
            )
        return result

    # --- dispatcher --------------------------------------------------------------
    def _dispatch(self, argv: list[str], command: RemoteCommand) -> tuple[int, str, str]:
        binary = argv[0]
        handler = getattr(self, f"_cmd_{binary.replace('-', '_')}", None)
        if handler is None:
            return 127, "", f"sh: {binary}: command not found"
        return handler(argv[1:], command)

    # system ----------------------------------------------------------------------
    def _cmd_cat(self, args, command):
        path = args[-1]
        if path == "/etc/os-release":
            return 0, self.state.os_release, ""
        data = self.state.files.get(path)
        if data is None:
            return 1, "", f"cat: {path}: No such file or directory"
        return 0, data.decode("utf-8", "replace"), ""

    def _cmd_uname(self, args, command):
        return 0, self.state.kernel + "\n", ""

    def _cmd_nproc(self, args, command):
        return 0, f"{self.state.nproc}\n", ""

    def _cmd_free(self, args, command):
        s = self.state
        used = s.mem_total_mb - s.mem_available_mb
        return 0, (
            "               total        used        free      shared  buff/cache   available\n"
            f"Mem:        {s.mem_total_mb:8d}    {used:8d}    {s.mem_available_mb - 1000:8d}         120        1000    {s.mem_available_mb:8d}\n"
            "Swap:              0           0           0\n"
        ), ""

    def _cmd_df(self, args, command):
        s = self.state
        used = s.disk_total_mb - s.disk_available_mb
        pct = int(used * 100 / s.disk_total_mb)
        return 0, (
            "Filesystem     1048576-blocks    Used Available Capacity Mounted on\n"
            f"/dev/mapper/ol-root   {s.disk_total_mb} {used} {s.disk_available_mb} {pct}% /\n"
        ), ""

    def _cmd_id(self, args, command):
        if "-un" in args:
            return 0, "scarlet\n", ""
        return 0, ("1001\n" if self.state.rootless else "0\n"), ""

    def _cmd_hostname(self, args, command):
        return 0, f"{self.label}.example.internal\n", ""

    def _cmd_getenforce(self, args, command):
        return 0, "Enforcing\n", ""

    def _cmd_command(self, args, command):
        binary = args[-1]
        available = {
            "podman": self.state.runtime == "podman",
            "docker": self.state.runtime == "docker",
            "kubectl": self.state.kubectl,
            "helm": False,
            "curl": True,
            "nc": True,
            "tar": True,
            "sha256sum": True,
        }
        if available.get(binary):
            return 0, f"/usr/bin/{binary}\n", ""
        return 1, "", ""

    def _cmd_true(self, args, command):
        return 0, "", ""

    # filesystem --------------------------------------------------------------------
    def _cmd_mkdir(self, args, command):
        path = args[-1]
        parts = PurePosixPath(path).parts
        for i in range(1, len(parts) + 1):
            self.state.dirs.add(str(PurePosixPath(*parts[:i])))
        return 0, "", ""

    def _cmd_test(self, args, command):
        flag, path = args[0], args[1]
        if flag == "-d":
            return (0 if path in self.state.dirs else 1), "", ""
        exists = path in self.state.dirs or path in self.state.files or path in self.state.symlinks
        return (0 if exists else 1), "", ""

    def _cmd_rm(self, args, command):
        path = args[-1]
        if "-rf" in args:
            for d in list(self.state.dirs):
                if d == path or d.startswith(path + "/"):
                    self.state.dirs.discard(d)
            for f in list(self.state.files):
                if f == path or f.startswith(path + "/"):
                    self.state.files.pop(f)
        else:
            self.state.files.pop(path, None)
        self.state.symlinks.pop(path, None)
        return 0, "", ""

    def _cmd_mv(self, args, command):
        src, dst = args[-2], args[-1]
        if src in self.state.symlinks:
            self.state.symlinks[dst] = self.state.symlinks.pop(src)
            return 0, "", ""
        if src in self.state.files:
            self.state.files[dst] = self.state.files.pop(src)
            return 0, "", ""
        if src in self.state.dirs:
            for d in list(self.state.dirs):
                if d == src or d.startswith(src + "/"):
                    self.state.dirs.discard(d)
                    self.state.dirs.add(dst + d[len(src):])
            for f in list(self.state.files):
                if f.startswith(src + "/"):
                    self.state.files[dst + f[len(src):]] = self.state.files.pop(f)
            return 0, "", ""
        return 1, "", f"mv: cannot stat '{src}': No such file or directory"

    def _cmd_ln(self, args, command):
        target, link = args[-2], args[-1]
        self.state.symlinks[link] = target
        return 0, "", ""

    def _cmd_readlink(self, args, command):
        link = args[-1]
        target = self.state.symlinks.get(link)
        if target is None:
            return 1, "", ""
        return 0, target + "\n", ""

    def _cmd_ls(self, args, command):
        path = args[-1]
        if path not in self.state.dirs:
            return 2, "", f"ls: cannot access '{path}': No such file or directory"
        entries = set()
        for d in self.state.dirs:
            if d.startswith(path + "/"):
                entries.add(d[len(path) + 1 :].split("/")[0])
        for f in list(self.state.files) + list(self.state.symlinks):
            if f.startswith(path + "/"):
                entries.add(f[len(path) + 1 :].split("/")[0])
        return 0, "".join(e + "\n" for e in sorted(entries)), ""

    def _cmd_sha256sum(self, args, command):
        path = args[-1]
        data = self.state.files.get(path)
        if data is None:
            return 1, "", f"sha256sum: {path}: No such file or directory"
        return 0, f"{hashlib.sha256(data).hexdigest()}  {path}\n", ""

    def _cmd_tar(self, args, command):
        import io
        import tarfile

        archive = args[args.index("-xzf") + 1]
        dest = args[args.index("-C") + 1]
        data = self.state.files.get(archive)
        if data is None:
            return 2, "", f"tar: {archive}: Cannot open: No such file or directory"
        if dest not in self.state.dirs:
            return 2, "", f"tar: {dest}: Cannot open: No such file or directory"
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
            for member in tar.getmembers():
                target = str(PurePosixPath(dest) / member.name)
                if member.isdir():
                    self.state.dirs.add(target)
                elif member.isfile():
                    self.state.dirs.add(str(PurePosixPath(target).parent))
                    extracted = tar.extractfile(member)
                    self.state.files[target] = extracted.read() if extracted else b""
        return 0, "", ""

    def _cmd_chmod(self, args, command):
        return 0, "", ""

    def _cmd_cp(self, args, command):
        src, dst = args[-2], args[-1]
        if src in self.state.files:
            self.state.files[dst] = self.state.files[src]
            return 0, "", ""
        return 1, "", "cp: no such file"

    def _cmd_find(self, args, command):
        return 0, "", ""

    def _cmd_timeout(self, args, command):
        # timeout N sh -e script
        script = args[-1]
        if script not in self.state.files:
            return 127, "", f"sh: {script}: No such file"
        self.state.hook_log.append(script)
        content = self.state.files[script].decode("utf-8", "replace")
        if "exit 1" in content:
            return 1, "", "hook failed"
        return 0, f"hook {PurePosixPath(script).name} executed\n", ""

    # health helpers --------------------------------------------------------------
    def _cmd_curl(self, args, command):
        url = args[-1]
        running = any(c.status == "running" for c in self.state.containers.values())
        if not running:
            return 7, "", "curl: (7) Failed to connect"
        return 0, str(self.state.health_http_status), ""

    def _cmd_nc(self, args, command):
        running = any(c.status == "running" for c in self.state.containers.values())
        return (0 if running else 1), "", ""

    # container runtime -------------------------------------------------------------
    def _cmd_podman(self, args, command):
        if self.state.runtime != "podman":
            return 127, "", "sh: podman: command not found"
        return self._container_cli(args, "podman")

    def _cmd_docker(self, args, command):
        if self.state.runtime != "docker":
            return 127, "", "sh: docker: command not found"
        return self._container_cli(args, "docker")

    def _container_cli(self, args: list[str], binary: str) -> tuple[int, str, str]:
        s = self.state
        sub = args[0]
        if sub == "version":
            return 0, s.runtime_version + "\n", ""
        if sub == "info":
            return 0, ("true" if s.rootless else "false") + "\n", ""
        if sub == "pull":
            s.images.add(args[-1])
            return 0, f"Pulled {args[-1]}\n", ""
        if sub == "load":
            path = args[args.index("-i") + 1]
            if path not in s.files:
                return 125, "", f"Error: open {path}: no such file or directory"
            image = s.files[path].decode("utf-8", "replace").strip() or "loaded/image:latest"
            s.images.add(image)
            return 0, f"Loaded image: {image}\n", ""
        if sub == "run":
            name = args[args.index("--name") + 1]
            image = args[-1]
            if name in s.containers and s.containers[name].status == "running":
                return 125, "", f"Error: container name {name} is already in use"
            labels = {}
            ports = []
            for i, a in enumerate(args):
                if a == "--label":
                    k, _, v = args[i + 1].partition("=")
                    labels[k] = v
                if a in {"-p", "--publish"}:
                    ports.append(args[i + 1])
            s.containers[name] = FakeContainer(name=name, image=image, labels=labels, ports=ports,
                                               logs=[f"{utcnow().isoformat()} INFO application started ({image})"])
            return 0, hashlib.sha256(name.encode()).hexdigest() + "\n", ""
        if sub in {"stop", "start", "restart", "rm", "kill"}:
            name = args[-1]
            c = s.containers.get(name)
            if c is None:
                if sub == "rm" and ("-f" in args or "--ignore" in args):
                    return 0, "", ""
                return 125, "", f"Error: no container with name or ID \"{name}\" found: no such container"
            if sub == "stop":
                c.status = "exited"
                c.logs.append(f"{utcnow().isoformat()} INFO application stopped")
            elif sub == "start":
                c.status = "running"
                c.logs.append(f"{utcnow().isoformat()} INFO application started")
            elif sub == "restart":
                c.status = "running"
                c.logs.append(f"{utcnow().isoformat()} INFO application restarted")
            elif sub == "rm":
                del s.containers[name]
            return 0, name + "\n", ""
        if sub == "ps":
            fmt_index = args.index("--format") if "--format" in args else -1
            rows = []
            for c in s.containers.values():
                if "-a" not in args and c.status != "running":
                    continue
                rows.append(json.dumps({"Names": [c.name], "Image": c.image, "State": c.status, "Labels": c.labels}))
            return 0, "\n".join(rows) + ("\n" if rows else ""), ""
        if sub == "inspect":
            name = args[-1]
            c = s.containers.get(name)
            if c is None:
                return 125, "", f"Error: no such object: {name}"
            fmt = args[args.index("--format") + 1] if "--format" in args else None
            payload = {
                "Id": hashlib.sha256(name.encode()).hexdigest(),
                "Name": name,
                "State": {"Status": c.status, "Running": c.status == "running", "ExitCode": c.exit_code,
                          "Health": {"Status": "healthy" if c.status == "running" else "unhealthy"}},
                "Config": {"Image": c.image, "Labels": c.labels},
                "ImageName": c.image,
            }
            if fmt == "{{json .}}" or fmt is None:
                return 0, json.dumps([payload]), ""
            if fmt == "{{.State.Status}}":
                return 0, c.status + "\n", ""
            return 0, json.dumps(payload), ""
        if sub == "logs":
            name = args[-1]
            c = s.containers.get(name)
            if c is None:
                return 125, "", f"Error: no container with name or ID \"{name}\" found"
            tail = None
            if "--tail" in args:
                tail = int(args[args.index("--tail") + 1])
            lines = c.logs[-tail:] if tail else c.logs
            return 0, "\n".join(lines) + "\n", ""
        if sub == "image":
            return 0, "", ""
        if sub == "exec":
            name = args[1] if args[1] != "--" else args[2]
            c = s.containers.get(name)
            if c is None or c.status != "running":
                return 125, "", "Error: container is not running"
            return 0, "ok\n", ""
        return 125, "", f"Error: unrecognized command `{binary} {sub}`"

    def _cmd_kubectl(self, args, command):
        if not self.state.kubectl:
            return 127, "", "sh: kubectl: command not found"
        if args[:1] == ["version"]:
            return 0, json.dumps({"clientVersion": {"gitVersion": "v1.30.2"}, "serverVersion": {"gitVersion": "v1.30.1"}}), ""
        return 0, "", ""


class FakeSSHClientFactory:
    """Drop-in replacement for ``SSHClientFactory`` keyed by host name."""

    def __init__(self) -> None:
        self.states: dict[str, FakeHostState] = {}
        self.default_state = FakeHostState()

    def state_for(self, host_name: str) -> FakeHostState:
        return self.states.setdefault(host_name, FakeHostState())

    def connect(self, host, **kwargs) -> FakeSSHClient:
        if host.active_credential is None:
            from app.errors import SSHAuthenticationError

            raise SSHAuthenticationError(f"Host '{host.name}' has no active SSH credential.")
        return FakeSSHClient(self.state_for(host.name), label=host.name)

    def build_params(self, host, **kwargs):  # pragma: no cover - compatibility
        return None


def local_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


__all__ = ["FakeContainer", "FakeHostState", "FakeSSHClient", "FakeSSHClientFactory", "local_sha256", "os", "shlex"]
