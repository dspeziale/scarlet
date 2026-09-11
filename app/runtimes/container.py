"""Docker and Podman runtime adapters.

Both CLIs share the same command surface, so a single ``ContainerCliAdapter``
implements the behaviour and the concrete classes only set the binary name and
the few runtime-specific flags (SELinux volume relabel for Podman, rootless
detection, restart policies).

Two execution modes are supported, chosen by the manifest:

* ``image`` mode: one container started with ``<cli> run``;
* ``compose`` mode: a compose file inside the release, driven with
  ``<cli> compose`` (Docker Compose v2 / Podman 4.1+ compose provider).
"""

from __future__ import annotations

import json
import re
import time
from typing import Any

from app.deployment.domain import ActualApplicationState, DesiredApplicationState, HealthSpec
from app.errors import (
    RemoteCommandError,
    RuntimeOperationError,
    UnsafeCommandError,
    ValidationError,
)
from app.models.enums import ApplicationState, HealthStatus, RuntimeType
from app.runtimes.base import (
    HealthResult,
    LogChunk,
    RuntimeAdapter,
    RuntimeContext,
    RuntimeDetection,
)
from app.security.validators import validate_container_name, validate_int_range
from app.ssh.command import RemoteCommand, SystemCommands, validate_remote_path

LABEL_APP = "scarlet.application"
LABEL_VERSION = "scarlet.version"
LABEL_MANAGED = "scarlet.managed"
_SINCE_RE = re.compile(r"^(\d{1,5}[smh]|\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}(:\d{2})?)?)$")
_STATUS_MAP = {
    "running": ApplicationState.RUNNING,
    "exited": ApplicationState.STOPPED,
    "stopped": ApplicationState.STOPPED,
    "created": ApplicationState.STOPPED,
    "paused": ApplicationState.STOPPED,
    "dead": ApplicationState.FAILED,
    "restarting": ApplicationState.STARTING,
    "removing": ApplicationState.STOPPING,
    "stopping": ApplicationState.STOPPING,
    "configured": ApplicationState.STOPPED,
    "unknown": ApplicationState.UNKNOWN,
}


class ContainerCliAdapter(RuntimeAdapter):
    binary = "docker"
    runtime_type = RuntimeType.DOCKER
    supports_image_load = True
    selinux_relabel = False

    # --- helpers -------------------------------------------------------------------------
    def _cmd(
        self,
        ctx: RuntimeContext,
        *args: str,
        command_type: str,
        description: str,
        allow_failure: bool = False,
        timeout: int | None = None,
    ) -> RemoteCommand:
        return RemoteCommand(
            (self.binary, *args),
            f"runtime.{self.binary}.{command_type}",
            description,
            allow_failure=allow_failure,
            timeout=timeout or ctx.timeout,
        )

    def _name(self, ctx: RuntimeContext) -> str:
        return validate_container_name(ctx.application_code)

    def _compose(
        self, desired: DesiredApplicationState | None, ctx: RuntimeContext
    ) -> dict[str, Any] | None:
        manifest = desired.manifest if desired else {}
        return manifest.get("compose") if manifest else None

    def _compose_args(
        self, ctx: RuntimeContext, compose: dict[str, Any], release_dir: str
    ) -> tuple[str, ...]:
        compose_file = validate_remote_path(
            f"{release_dir}/{compose['file']}", ctx.layout.base_path
        )
        project = compose.get("project_name") or ctx.application_code
        return (
            "compose",
            "--project-name",
            validate_container_name(project),
            "--file",
            compose_file,
        )

    def _current_release_dir(self, ctx: RuntimeContext) -> str | None:
        result = ctx.run(ctx.layout and self._readlink_cmd(ctx), label="Resolve current release")
        target = result.stdout.strip()
        if not result.ok or not target:
            return None
        try:
            return validate_remote_path(target, ctx.layout.base_path)
        except UnsafeCommandError:
            return None

    def _readlink_cmd(self, ctx: RuntimeContext) -> RemoteCommand:
        from app.ssh.command import FileCommands

        return FileCommands(ctx.layout.base_path).readlink(ctx.layout.current_link)

    def _inspect_raw(self, ctx: RuntimeContext) -> dict[str, Any] | None:
        result = ctx.run(
            self._cmd(
                ctx,
                "inspect",
                "--type",
                "container",
                "--format",
                "{{json .}}",
                self._name(ctx),
                command_type="inspect",
                description="Inspect container",
                allow_failure=True,
            ),
            label="Inspect container",
        )
        if not result.ok:
            return None
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            return None
        if isinstance(data, list):
            data = data[0] if data else None
        return data if isinstance(data, dict) else None

    @staticmethod
    def _labels(data: dict[str, Any]) -> dict[str, str]:
        config = data.get("Config") or {}
        labels = config.get("Labels") or data.get("Labels") or {}
        return labels if isinstance(labels, dict) else {}

    # --- detection -------------------------------------------------------------------------
    def detect(self, ctx: RuntimeContext) -> RuntimeDetection:
        which = ctx.run(SystemCommands.which(self.binary), label=f"Locate {self.binary}")
        if not which.ok:
            return RuntimeDetection(
                self.runtime_type.value,
                False,
                details={"reason": f"{self.binary} not found in PATH"},
            )
        version = ctx.run(
            SystemCommands.runtime_version(self.binary), label=f"{self.binary} version"
        )
        detection = RuntimeDetection(
            self.runtime_type.value,
            available=version.ok,
            version=version.stdout.strip() or None,
            binary_path=which.stdout.strip() or None,
            details={} if version.ok else {"reason": version.stderr.strip()[:500]},
        )
        if self.binary == "podman" and version.ok:
            rootless = ctx.run(SystemCommands.podman_info_rootless(), label="Podman rootless")
            if rootless.ok:
                detection.rootless = rootless.stdout.strip().lower() == "true"
        elif version.ok:
            uid = ctx.run(SystemCommands.uid(), label="Remote uid")
            detection.rootless = uid.ok and uid.stdout.strip() != "0"
        return detection

    # --- observation -----------------------------------------------------------------------
    def status(self, ctx: RuntimeContext) -> ActualApplicationState:
        data = self._inspect_raw(ctx)
        actual = ActualApplicationState(
            application_code=ctx.application_code, runtime=self.runtime_type.value
        )
        if data is None:
            # container missing: installed release?
            release = self._current_release_dir(ctx)
            if release:
                actual.state = ApplicationState.STOPPED
                actual.version = release.rstrip("/").split("/")[-1]
                actual.message = "Release installed but no container exists."
            else:
                actual.state = ApplicationState.NOT_INSTALLED
                actual.message = "No container and no installed release."
            return actual
        state = data.get("State") or {}
        status = str(state.get("Status") or "unknown").lower()
        actual.state = _STATUS_MAP.get(status, ApplicationState.UNKNOWN)
        labels = self._labels(data)
        actual.version = labels.get(LABEL_VERSION)
        actual.image = (data.get("Config") or {}).get("Image") or data.get("ImageName")
        actual.replicas = 1 if actual.state == ApplicationState.RUNNING else 0
        health = (state.get("Health") or {}).get("Status")
        if health == "healthy":
            actual.health = HealthStatus.HEALTHY
        elif health == "unhealthy":
            actual.health = HealthStatus.UNHEALTHY
        actual.details = {
            "container_id": (data.get("Id") or "")[:12],
            "status": status,
            "exit_code": state.get("ExitCode"),
            "started_at": state.get("StartedAt"),
            "finished_at": state.get("FinishedAt"),
            "image": actual.image,
            "labels": {k: v for k, v in labels.items() if k.startswith("scarlet.")},
        }
        return actual

    def version(self, ctx: RuntimeContext) -> str | None:
        data = self._inspect_raw(ctx)
        if data:
            version = self._labels(data).get(LABEL_VERSION)
            if version:
                return version
        release = self._current_release_dir(ctx)
        return release.rstrip("/").split("/")[-1] if release else None

    def inspect(self, ctx: RuntimeContext) -> dict[str, Any]:
        data = self._inspect_raw(ctx) or {}
        # Strip environment (may contain secrets) before returning
        config = dict(data.get("Config") or {})
        config.pop("Env", None)
        return {
            "Id": data.get("Id"),
            "Name": data.get("Name"),
            "State": data.get("State"),
            "Config": {
                k: config.get(k) for k in ("Image", "Labels", "User", "WorkingDir", "ExposedPorts")
            },
            "RestartCount": data.get("RestartCount"),
            "HostConfig": {
                k: (data.get("HostConfig") or {}).get(k)
                for k in ("RestartPolicy", "PortBindings", "Memory", "NanoCpus")
            },
        }

    def logs(self, ctx: RuntimeContext, lines: int = 200, since: str | None = None) -> LogChunk:
        lines = validate_int_range(lines, field="lines", minimum=1, maximum=5000)
        args = ["logs", "--timestamps", "--tail", str(lines)]
        if since:
            if not _SINCE_RE.match(since):
                raise ValidationError(
                    "Invalid 'since' value.", errors={"since": ["Use 10m, 2h or an ISO date."]}
                )
            args += ["--since", since]
        args.append(self._name(ctx))
        result = ctx.run(
            self._cmd(
                ctx,
                *args,
                command_type="logs",
                description="Collect logs",
                allow_failure=True,
                timeout=60,
            ),
            label="Collect logs",
        )
        if not result.ok:
            raise RuntimeOperationError(
                f"Unable to collect logs: {result.stderr.strip()[:300] or 'container not found'}"
            )
        text = (result.stdout or "") + (("\n" + result.stderr) if result.stderr else "")
        out = [line for line in text.splitlines() if line.strip()]
        return LogChunk(
            lines=out[-lines:],
            source=f"{self.binary} logs {self._name(ctx)}",
            truncated=len(out) > lines,
        )

    def health(
        self, ctx: RuntimeContext, spec: HealthSpec, desired: DesiredApplicationState | None = None
    ) -> HealthResult:
        t0 = time.monotonic()
        check = spec.check_type.upper()
        if check in {"HTTP", "HTTPS"}:
            port = spec.port or (desired.health.port if desired else None)
            if not port:
                return HealthResult(HealthStatus.UNKNOWN, "No health port configured.")
            url = f"{check.lower()}://127.0.0.1:{int(port)}{spec.path}"
            cmd = RemoteCommand(
                (
                    "curl",
                    "-k",
                    "-s",
                    "-S",
                    "-o",
                    "/dev/null",
                    "-w",
                    "%{http_code}",
                    "--max-time",
                    str(int(spec.timeout)),
                    url,
                ),
                "health.http",
                "HTTP health probe",
                allow_failure=True,
                timeout=spec.timeout + 5,
            )
            result = ctx.run(cmd, label="HTTP health probe")
            code = result.stdout.strip()
            if result.ok and code.isdigit() and int(code) == spec.expected_status:
                return HealthResult(
                    HealthStatus.HEALTHY,
                    f"HTTP {code}",
                    details={"url": url, "status_code": int(code)},
                    duration_seconds=round(time.monotonic() - t0, 3),
                )
            return HealthResult(
                HealthStatus.UNHEALTHY,
                f"HTTP probe failed (status={code or 'n/a'}, exit={result.exit_code})",
                details={"url": url, "stderr": result.stderr[:300]},
                duration_seconds=round(time.monotonic() - t0, 3),
            )
        if check == "TCP":
            port = spec.port or (desired.health.port if desired else None)
            if not port:
                return HealthResult(HealthStatus.UNKNOWN, "No health port configured.")
            cmd = RemoteCommand(
                ("nc", "-z", "-w", str(int(spec.timeout)), "127.0.0.1", str(int(port))),
                "health.tcp",
                "TCP health probe",
                allow_failure=True,
                timeout=spec.timeout + 5,
            )
            result = ctx.run(cmd, label="TCP health probe")
            status = HealthStatus.HEALTHY if result.ok else HealthStatus.UNHEALTHY
            return HealthResult(
                status,
                f"TCP port {port} {'open' if result.ok else 'closed'}",
                duration_seconds=round(time.monotonic() - t0, 3),
            )
        if check == "COMMAND":
            argv = spec.command or (desired.health.command if desired else ())
            if not argv:
                return HealthResult(HealthStatus.UNKNOWN, "No health command configured.")
            cmd = self._cmd(
                ctx,
                "exec",
                self._name(ctx),
                *argv,
                command_type="exec_health",
                description="Command health probe",
                allow_failure=True,
                timeout=spec.timeout + 5,
            )
            result = ctx.run(cmd, label="Command health probe")
            status = HealthStatus.HEALTHY if result.ok else HealthStatus.UNHEALTHY
            return HealthResult(
                status,
                f"exit code {result.exit_code}",
                details={"stdout": result.stdout[:300]},
                duration_seconds=round(time.monotonic() - t0, 3),
            )
        # CONTAINER_STATUS (default)
        actual = self.status(ctx)
        if actual.state == ApplicationState.RUNNING and actual.health != HealthStatus.UNHEALTHY:
            return HealthResult(
                HealthStatus.HEALTHY,
                "Container is running",
                details=actual.details,
                duration_seconds=round(time.monotonic() - t0, 3),
            )
        return HealthResult(
            HealthStatus.UNHEALTHY,
            f"Container state is {actual.state.value}",
            details=actual.details,
            duration_seconds=round(time.monotonic() - t0, 3),
        )

    # --- mutation ---------------------------------------------------------------------------------
    def install(
        self, ctx: RuntimeContext, desired: DesiredApplicationState, release_dir: str
    ) -> dict[str, Any]:
        release_dir = validate_remote_path(release_dir, ctx.layout.base_path)
        compose = self._compose(desired, ctx)
        if compose:
            args = self._compose_args(ctx, compose, release_dir)
            result = ctx.run(
                self._cmd(
                    ctx,
                    *args,
                    "pull",
                    "--ignore-buildable",
                    command_type="compose_pull",
                    description="Pull compose images",
                    allow_failure=True,
                    timeout=max(ctx.timeout, 900),
                ),
                label="Pull compose images",
            )
            if not result.ok:
                # older compose versions lack --ignore-buildable
                ctx.run(
                    self._cmd(
                        ctx,
                        *args,
                        "pull",
                        command_type="compose_pull",
                        description="Pull compose images",
                        timeout=max(ctx.timeout, 900),
                    ),
                    label="Pull compose images",
                )
            return {"mode": "compose"}
        image = desired.manifest.get("image") or {}
        reference = desired.image
        if not reference:
            raise RuntimeOperationError("The manifest does not declare an image.")
        policy = image.get("pull_policy", "if-not-present")
        archive = image.get("archive")
        if archive:
            archive_path = validate_remote_path(f"{release_dir}/{archive}", ctx.layout.base_path)
            ctx.run(
                self._cmd(
                    ctx,
                    "load",
                    "-i",
                    archive_path,
                    command_type="load",
                    description="Load image archive",
                    timeout=max(ctx.timeout, 900),
                ),
                label="Load image archive",
            )
            return {"mode": "image", "image": reference, "source": "archive"}
        if policy == "never":
            raise RuntimeOperationError("pull_policy is 'never' but no image archive is present.")
        if policy == "if-not-present":
            exists = ctx.run(
                self._cmd(
                    ctx,
                    "image",
                    "exists",
                    reference,
                    command_type="image_exists",
                    description="Check image",
                    allow_failure=True,
                ),
                label="Check image",
            )
            if exists.ok:
                return {"mode": "image", "image": reference, "source": "local"}
        ctx.run(
            self._cmd(
                ctx,
                "pull",
                reference,
                command_type="pull",
                description=f"Pull image {reference}",
                timeout=max(ctx.timeout, 900),
            ),
            label="Pull image",
        )
        return {"mode": "image", "image": reference, "source": "registry"}

    def _run_args(self, ctx: RuntimeContext, desired: DesiredApplicationState) -> list[str]:
        manifest = desired.manifest
        deployment = manifest.get("deployment") or {}
        resources = manifest.get("resources") or {}
        args: list[str] = [
            "run",
            "-d",
            "--name",
            self._name(ctx),
            "--label",
            f"{LABEL_APP}={ctx.application_code}",
            "--label",
            f"{LABEL_VERSION}={desired.version}",
            "--label",
            f"{LABEL_MANAGED}=true",
            "--env-file",
            ctx.layout.env_file,
            "--restart",
            self._restart_policy(deployment.get("restart_policy", "unless-stopped")),
        ]
        for port in desired.ports:
            args += ["-p", port]
        for volume in desired.volumes:
            args += ["-v", volume + (":Z" if self.selinux_relabel and ":ro" not in volume else "")]
        if resources.get("memory"):
            mem = resources["memory"].replace("Ki", "k").replace("Mi", "m").replace("Gi", "g")
            args += ["--memory", mem]
        if resources.get("cpu"):
            cpu = resources["cpu"]
            cpu = str(int(cpu[:-1]) / 1000) if cpu.endswith("m") else cpu
            args += ["--cpus", cpu]
        if deployment.get("user"):
            args += ["--user", str(deployment["user"])]
        if deployment.get("read_only_rootfs"):
            args += ["--read-only"]
        if deployment.get("stop_grace_period") is not None:
            args += ["--stop-timeout", str(int(deployment["stop_grace_period"]))]
        args.append(desired.image or "")
        return args

    def _restart_policy(self, policy: str) -> str:
        allowed = {"always", "unless-stopped", "on-failure", "no"}
        if policy not in allowed:
            raise ValidationError("Invalid restart policy.")
        return policy

    def start(
        self, ctx: RuntimeContext, desired: DesiredApplicationState
    ) -> ActualApplicationState:
        compose = self._compose(desired, ctx)
        if compose:
            release_dir = ctx.layout.release_dir(desired.version)
            args = self._compose_args(ctx, compose, release_dir)
            ctx.run(
                self._cmd(
                    ctx,
                    *args,
                    "--env-file",
                    ctx.layout.env_file,
                    "up",
                    "-d",
                    "--remove-orphans",
                    command_type="compose_up",
                    description="Compose up",
                    timeout=max(ctx.timeout, 600),
                ),
                label="Compose up",
            )
            return self.status(ctx)
        actual = self.status(ctx)
        if actual.state == ApplicationState.RUNNING and actual.version == desired.version:
            actual.message = "ALREADY_RUNNING"
            return actual
        if actual.state in {
            ApplicationState.STOPPED,
            ApplicationState.FAILED,
        } and actual.details.get("container_id"):
            # existing container: same version -> start it, different version -> recreate
            if actual.version == desired.version:
                ctx.run(
                    self._cmd(
                        ctx,
                        "start",
                        self._name(ctx),
                        command_type="start",
                        description="Start container",
                    ),
                    label="Start container",
                )
                return self.status(ctx)
            ctx.run(
                self._cmd(
                    ctx,
                    "rm",
                    "-f",
                    self._name(ctx),
                    command_type="rm",
                    description="Remove old container",
                    allow_failure=True,
                ),
                label="Remove old container",
            )
        elif actual.state == ApplicationState.RUNNING:
            # running with a different version: recreate
            self.stop(ctx)
            ctx.run(
                self._cmd(
                    ctx,
                    "rm",
                    "-f",
                    self._name(ctx),
                    command_type="rm",
                    description="Remove old container",
                    allow_failure=True,
                ),
                label="Remove old container",
            )
        result = ctx.run(
            self._cmd(
                ctx, *self._run_args(ctx, desired), command_type="run", description="Run container"
            ),
            label="Run container",
        )
        status = self.status(ctx)
        status.details["container_id"] = (
            status.details.get("container_id") or result.stdout.strip()[:12]
        )
        return status

    def stop(self, ctx: RuntimeContext) -> ActualApplicationState:
        actual = self.status(ctx)
        if actual.state in {ApplicationState.STOPPED, ApplicationState.NOT_INSTALLED}:
            actual.message = "ALREADY_STOPPED"
            return actual
        release_dir = self._current_release_dir(ctx)
        compose = None
        if release_dir:
            compose = self._compose_from_release(ctx, release_dir)
        if compose:
            args = self._compose_args(ctx, compose, release_dir)
            ctx.run(
                self._cmd(
                    ctx,
                    *args,
                    "stop",
                    command_type="compose_stop",
                    description="Compose stop",
                    timeout=300,
                ),
                label="Compose stop",
            )
        else:
            ctx.run(
                self._cmd(
                    ctx,
                    "stop",
                    self._name(ctx),
                    command_type="stop",
                    description="Stop container",
                    timeout=300,
                ),
                label="Stop container",
            )
        result = self.status(ctx)
        result.message = "STOPPED"
        return result

    def _compose_from_release(self, ctx: RuntimeContext, release_dir: str) -> dict[str, Any] | None:
        """Read manifest.yaml of the active release to know whether compose mode is used."""
        from app.ssh.command import FileCommands

        try:
            result = ctx.run(
                FileCommands(ctx.layout.base_path).cat(f"{release_dir}/manifest.yaml"),
                label="Read release manifest",
            )
        except RemoteCommandError:
            return None
        if not result.ok:
            return None
        try:
            import yaml

            data = yaml.safe_load(result.stdout) or {}
        except Exception:  # noqa: BLE001
            return None
        compose = data.get("compose") if isinstance(data, dict) else None
        return compose if isinstance(compose, dict) and compose.get("file") else None

    def restart(
        self, ctx: RuntimeContext, desired: DesiredApplicationState
    ) -> ActualApplicationState:
        compose = self._compose(desired, ctx)
        if compose:
            args = self._compose_args(ctx, compose, ctx.layout.release_dir(desired.version))
            ctx.run(
                self._cmd(
                    ctx,
                    *args,
                    "restart",
                    command_type="compose_restart",
                    description="Compose restart",
                    timeout=600,
                ),
                label="Compose restart",
            )
            return self.status(ctx)
        actual = self.status(ctx)
        if actual.details.get("container_id") and actual.version == desired.version:
            ctx.run(
                self._cmd(
                    ctx,
                    "restart",
                    self._name(ctx),
                    command_type="restart",
                    description="Restart container",
                    timeout=600,
                ),
                label="Restart container",
            )
            return self.status(ctx)
        return self.start(ctx, desired)

    def remove(self, ctx: RuntimeContext) -> None:
        release_dir = self._current_release_dir(ctx)
        compose = self._compose_from_release(ctx, release_dir) if release_dir else None
        if compose and release_dir:
            args = self._compose_args(ctx, compose, release_dir)
            ctx.run(
                self._cmd(
                    ctx,
                    *args,
                    "down",
                    "--remove-orphans",
                    command_type="compose_down",
                    description="Compose down",
                    allow_failure=True,
                    timeout=600,
                ),
                label="Compose down",
            )
            return
        ctx.run(
            self._cmd(
                ctx,
                "rm",
                "-f",
                self._name(ctx),
                command_type="rm",
                description="Remove container",
                allow_failure=True,
            ),
            label="Remove container",
        )


class DockerRuntimeAdapter(ContainerCliAdapter):
    binary = "docker"
    runtime_type = RuntimeType.DOCKER
    selinux_relabel = False


class PodmanRuntimeAdapter(ContainerCliAdapter):
    binary = "podman"
    runtime_type = RuntimeType.PODMAN
    selinux_relabel = True

    def _restart_policy(self, policy: str) -> str:
        # Podman: "unless-stopped" is accepted since 4.x; map for older versions is documented.
        return super()._restart_policy(policy)
