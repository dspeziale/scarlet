"""Deployment engine: executes a DeploymentPlan against a target host.

The engine owns the pipeline mechanics (state machine, step records, locking,
rollback decision); the runtime adapter owns *how* install/start/health are
performed on Docker, Podman or Kubernetes.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import time
from collections.abc import Callable
from typing import Any

from flask import current_app

from app.audit import audit
from app.config.logging import bind_context, get_logger, redact, reset_context
from app.deployment.domain import (
    ActualApplicationState,
    DeploymentExecution,
    DesiredApplicationState,
    PlanStep,
    StepExecution,
)
from app.deployment.planner import DeploymentPlanner, build_desired_state
from app.deployment.remote_layout import RemoteLayout
from app.deployment.state_machine import DeploymentStateMachine
from app.deployment.storage import get_artifact_storage
from app.deployment.validator import safe_extract, sha256_file
from app.errors import (
    DeploymentError,
    FileTransferError,
    HealthCheckError,
    PreflightError,
    ScarletError,
    ValidationError,
)
from app.extensions import db
from app.lifecycle.health import HealthChecker
from app.lifecycle.locks import get_lock_manager, runtime_lock_key
from app.models.deployment import Deployment, DeploymentStep
from app.models.enums import (
    ApplicationState,
    AuditResult,
    DeploymentKind,
    DeploymentStatus,
    DesiredState,
    HealthStatus,
    NotificationLevel,
    RuntimeType,
    StepStatus,
)
from app.models.lifecycle import HealthCheck
from app.repositories import InstanceRepository, VersionRepository
from app.runtimes.base import HostInfo, RuntimeAdapter, RuntimeContext
from app.runtimes.factory import RuntimeFactory
from app.security.crypto import get_cipher
from app.services.configuration_service import ConfigurationService
from app.services.notification_service import notify_operators
from app.services.preflight_service import PreflightService
from app.ssh.command import FileCommands
from app.ssh.factory import get_ssh_factory
from app.utils.ids import new_token
from app.utils.time import duration_seconds, utcnow

log = get_logger(__name__)

STEP_STATES: dict[str, tuple[DeploymentStatus | None, DeploymentStatus | None]] = {
    "validate": (DeploymentStatus.VALIDATING, DeploymentStatus.VALIDATED),
    "preflight": (DeploymentStatus.PREFLIGHT, None),
    "transfer": (DeploymentStatus.TRANSFERRING, None),
    "verify_checksum": (None, DeploymentStatus.TRANSFERRED),
    "extract": (DeploymentStatus.INSTALLING, None),
    "install": (None, None),
    "activate": (None, DeploymentStatus.INSTALLED),
    "start": (DeploymentStatus.STARTING, DeploymentStatus.STARTED),
    "health": (DeploymentStatus.HEALTH_CHECKING, None),
    "finalize": (None, DeploymentStatus.SUCCESS),
}


class StepLogger:
    """Collects command output for the DeploymentStep currently executing."""

    def __init__(self) -> None:
        self.stdout: list[str] = []
        self.stderr: list[str] = []
        self.last_exit: int | None = None
        self.messages: list[str] = []

    def __call__(self, level: str, message: str, result=None) -> None:
        self.messages.append(f"[{level}] {message}")
        if result is not None:
            self.stdout.append(f"$ {result.command}\n{result.stdout}".rstrip())
            if result.stderr:
                self.stderr.append(result.stderr.rstrip())
            self.last_exit = result.exit_code

    def reset(self) -> None:
        self.__init__()

    def stdout_text(self) -> str:
        return redact("\n".join(self.messages + self.stdout))[:200_000]

    def stderr_text(self) -> str:
        return redact("\n".join(self.stderr))[:100_000]


class DeploymentEngine:
    def __init__(self, sleep: Callable[[float], None] = time.sleep) -> None:
        self.instances = InstanceRepository()
        self.versions = VersionRepository()
        self.config = ConfigurationService()
        self.planner = DeploymentPlanner()
        self._sleep = sleep

    # --- entry point ---------------------------------------------------------------------------
    def execute(self, deployment_id: int, job_id: str | None = None) -> DeploymentExecution:
        deployment = db.session.get(Deployment, deployment_id)
        if deployment is None:
            raise DeploymentError(f"Deployment {deployment_id} not found.")
        token = bind_context(
            deployment_id=deployment.reference,
            application_id=deployment.application_id,
            target_id=deployment.target_id,
            request_id=deployment.request_id,
            job_id=job_id,
        )
        try:
            return self._execute(deployment, job_id)
        finally:
            reset_context(token)

    def _execute(self, deployment: Deployment, job_id: str | None) -> DeploymentExecution:
        sm = DeploymentStateMachine(deployment)
        if sm.is_terminal:
            raise DeploymentError(
                f"Deployment {deployment.reference} is already {deployment.status}."
            )
        if sm.state == DeploymentStatus.PENDING_APPROVAL:
            raise DeploymentError("Deployment is waiting for approval.")
        if sm.state in {DeploymentStatus.CREATED, DeploymentStatus.APPROVED}:
            sm.transition(DeploymentStatus.QUEUED)
        deployment.job_id = job_id or deployment.job_id
        deployment.started_at = utcnow()
        db.session.commit()

        application = deployment.application
        version = deployment.version
        host = deployment.target
        environment = deployment.environment
        lock = get_lock_manager()
        try:
            with lock.hold(
                runtime_lock_key(host.id, application.id),
                ttl=int(current_app.config.get("SCARLET_DEPLOYMENT_TIMEOUT", 1800)) + 60,
                description=f"{application.code} on {host.name}",
            ):
                return self._run_pipeline(deployment, sm, application, version, host, environment)
        except ScarletError as exc:
            if not sm.is_terminal:
                sm.fail(code=exc.code, message=exc.message)
                deployment.completed_at = utcnow()
                deployment.duration_seconds = duration_seconds(
                    deployment.started_at, deployment.completed_at
                )
                db.session.commit()
            self._audit_result(deployment, success=False, error=exc.message)
            raise

    # --- pipeline -------------------------------------------------------------------------------------
    def _run_pipeline(
        self, deployment, sm, application, version, host, environment
    ) -> DeploymentExecution:
        env_vars, missing = self.config.render_environment(
            application, environment, version.manifest or {}
        )
        if missing:
            raise PreflightError(f"Missing secrets: {', '.join(missing)}")
        desired = build_desired_state(application, version, host, env_vars)
        instance = self.instances.get_or_create(application.id, host.id)
        previous_version = (
            instance.current_version.version
            if instance.current_version and instance.current_version_id != version.id
            else None
        )
        if (
            deployment.kind == DeploymentKind.ROLLBACK.value
            and deployment.previous_version is not None
        ):
            previous_version = deployment.previous_version.version
        plan = self.planner.plan(
            reference=deployment.reference,
            application=application,
            version=version,
            host=host,
            desired=desired,
            previous_version=previous_version,
            kind=deployment.kind,
            auto_rollback=deployment.auto_rollback,
        )
        deployment.plan = plan.to_dict()
        deployment.instance_id = instance.id
        if (
            deployment.kind == DeploymentKind.DEPLOY.value
            and instance.current_version_id
            and instance.current_version_id != version.id
        ):
            deployment.previous_version_id = instance.current_version_id
        # desired state is recorded up-front: the control plane now *wants* this version
        instance.desired_version_id = version.id
        instance.desired_state = DesiredState.RUNNING.value
        instance.desired_replicas = desired.replicas
        instance.desired_updated_at = utcnow()
        instance.desired_updated_by_id = deployment.requested_by_id
        instance.last_deployment_id = deployment.id
        # step rows
        for existing in list(deployment.steps):
            db.session.delete(existing)
        step_rows: dict[str, DeploymentStep] = {}
        for index, step in enumerate(plan.steps, start=1):
            row = DeploymentStep(
                deployment_id=deployment.id,
                sequence=index,
                name=step.name,
                label=step.label,
                status=StepStatus.PENDING.value,
            )
            db.session.add(row)
            step_rows[step.name] = row
        db.session.commit()

        execution = DeploymentExecution(
            plan=plan, steps=[StepExecution(step=s) for s in plan.steps]
        )
        base = host.remote_base_path or current_app.config["SCARLET_REMOTE_BASE_PATH"]
        layout = RemoteLayout(base, application.code)
        adapter = RuntimeFactory.get(host.runtime_type)
        info = HostInfo(
            name=host.name,
            runtime_type=host.runtime_type,
            base_path=base,
            rootless=host.runtime_rootless,
            kubernetes_namespace=host.kubernetes_namespace,
            kubernetes_context=host.kubernetes_context,
            architecture=host.architecture,
        )
        if (
            host.runtime_type == RuntimeType.KUBERNETES.value
            and host.kubernetes_credential is not None
        ):
            info.kubeconfig = get_cipher().decrypt(host.kubernetes_credential.encrypted_secret)
        step_logger = StepLogger()
        timeout = int(current_app.config.get("SCARLET_SSH_COMMAND_TIMEOUT", 600))
        state: dict[str, Any] = {
            "token": new_token(6).replace("-", "").replace("_", "")[:8].lower(),
            "activated": False,
            "local_dir": None,
            "previous_version": previous_version,
        }
        deadline = time.monotonic() + int(
            current_app.config.get("SCARLET_DEPLOYMENT_TIMEOUT", 1800)
        )
        factory = get_ssh_factory()
        client = factory.connect(host)
        ctx = RuntimeContext(
            executor=client,
            host=info,
            application_code=application.code,
            layout=layout,
            log=step_logger,
            timeout=timeout,
        )
        failed_step: StepExecution | None = None
        error: ScarletError | None = None
        try:
            for step_exec in execution.steps:
                step = step_exec.step
                row = step_rows[step.name]
                if time.monotonic() > deadline:
                    raise DeploymentError(
                        "Deployment timeout exceeded.", details={"step": step.name}
                    )
                self._begin_step(sm, deployment, step, step_exec, row)
                step_logger.reset()
                try:
                    details = (
                        self._run_step(
                            step,
                            ctx,
                            adapter,
                            deployment,
                            application,
                            version,
                            host,
                            environment,
                            desired,
                            instance,
                            state,
                            execution,
                        )
                        or {}
                    )
                    self._end_step(
                        sm,
                        deployment,
                        step,
                        step_exec,
                        row,
                        StepStatus.SUCCESS,
                        step_logger,
                        details,
                    )
                except ScarletError as exc:
                    self._end_step(
                        sm,
                        deployment,
                        step,
                        step_exec,
                        row,
                        StepStatus.FAILED,
                        step_logger,
                        {},
                        error=exc,
                    )
                    if step.critical:
                        failed_step = step_exec
                        error = exc
                        break
                    execution.steps[execution.steps.index(step_exec)].status = StepStatus.FAILED
            if failed_step is None:
                execution.status = "SUCCESS"
            else:
                assert error is not None
                execution.status = "FAILED"
                execution.error_code = error.code
                execution.error_message = error.message
                self._handle_failure(
                    sm,
                    deployment,
                    failed_step,
                    error,
                    ctx,
                    adapter,
                    application,
                    host,
                    instance,
                    state,
                    execution,
                    step_rows,
                )
        finally:
            execution.completed_at = utcnow()
            if state.get("local_dir"):
                shutil.rmtree(state["local_dir"], ignore_errors=True)
            try:
                client.close()
            except Exception:  # noqa: BLE001
                pass
            info.kubeconfig = None
        deployment.completed_at = utcnow()
        deployment.duration_seconds = duration_seconds(
            deployment.started_at, deployment.completed_at
        )
        deployment.result_summary = execution.to_dict()
        db.session.commit()
        if execution.status == "SUCCESS":
            self._audit_result(deployment, success=True)
        else:
            self._audit_result(deployment, success=False, error=execution.error_message)
            if error is not None:
                raise error
        return execution

    # --- step bookkeeping -----------------------------------------------------------------------------
    def _begin_step(
        self, sm, deployment, step: PlanStep, step_exec: StepExecution, row: DeploymentStep
    ) -> None:
        enter, _ = STEP_STATES.get(step.kind, (None, None))
        if enter is not None and sm.state != enter and not sm.is_terminal:
            try:
                sm.transition(enter)
            except ScarletError:
                pass
        step_exec.status = StepStatus.RUNNING
        step_exec.started_at = utcnow()
        row.status = StepStatus.RUNNING.value
        row.started_at = step_exec.started_at
        db.session.commit()

    def _end_step(
        self,
        sm,
        deployment,
        step: PlanStep,
        step_exec: StepExecution,
        row: DeploymentStep,
        status: StepStatus,
        logger: StepLogger,
        details: dict[str, Any],
        error: ScarletError | None = None,
    ) -> None:
        step_exec.status = status
        step_exec.completed_at = utcnow()
        step_exec.stdout = logger.stdout_text()
        step_exec.stderr = logger.stderr_text()
        step_exec.exit_code = logger.last_exit
        step_exec.details = details
        row.status = status.value
        row.completed_at = step_exec.completed_at
        row.duration_seconds = step_exec.duration_seconds
        row.stdout = step_exec.stdout
        row.stderr = step_exec.stderr
        row.exit_code = logger.last_exit
        row.details = details
        if error is not None:
            message = redact(error.message)
            stderr = getattr(error, "stderr", "")
            if stderr:
                row.stderr = (row.stderr or "") + "\n" + redact(str(stderr))[:20000]
            step_exec.error_message = message
            row.error_message = message[:4000]
            if step.critical:
                sm.fail(code=error.code, message=message)
        else:
            _, leave = STEP_STATES.get(step.kind, (None, None))
            if leave is not None and not sm.is_terminal:
                try:
                    sm.transition(leave)
                except ScarletError:
                    pass
        db.session.commit()

    # --- step handlers -------------------------------------------------------------------------------------
    def _run_step(
        self,
        step: PlanStep,
        ctx: RuntimeContext,
        adapter: RuntimeAdapter,
        deployment,
        application,
        version,
        host,
        environment,
        desired: DesiredApplicationState,
        instance,
        state: dict[str, Any],
        execution: DeploymentExecution,
    ) -> dict[str, Any] | None:
        handler = getattr(self, f"_step_{step.kind}", None)
        if handler is None:
            raise DeploymentError(f"Unknown plan step kind {step.kind}.")
        return handler(
            step,
            ctx,
            adapter,
            deployment,
            application,
            version,
            host,
            environment,
            desired,
            instance,
            state,
            execution,
        )

    def _step_validate(
        self,
        step,
        ctx,
        adapter,
        deployment,
        application,
        version,
        host,
        environment,
        desired,
        instance,
        state,
        execution,
    ):
        storage = get_artifact_storage()
        if version.package is None or not storage.exists(version.package.storage_key):
            raise ValidationError("Release artifact not found in storage.")
        local_path = storage.local_path(version.package.storage_key)
        checksum = sha256_file(local_path)
        if checksum != version.checksum_sha256:
            raise ValidationError(
                "Artifact checksum does not match the immutable release checksum."
            )
        state["local_path"] = local_path
        ctx.log(
            "INFO",
            f"Package {version.package.original_filename} verified (sha256 {checksum[:12]}...)",
        )
        if host.runtime_type == RuntimeType.KUBERNETES.value and ctx.host.kubeconfig:
            local_dir = tempfile.mkdtemp(prefix="scarlet-k8s-")
            safe_extract(
                local_path,
                local_dir,
                max_members=int(current_app.config.get("SCARLET_MAX_PACKAGE_MEMBERS", 20000)),
            )
            state["local_dir"] = local_dir
            ctx.local_release_dir = local_dir
        return {"checksum": checksum, "size_bytes": os.path.getsize(local_path)}

    def _step_preflight(
        self,
        step,
        ctx,
        adapter,
        deployment,
        application,
        version,
        host,
        environment,
        desired,
        instance,
        state,
        execution,
    ):
        detection = adapter.detect(ctx)
        if not detection.available:
            raise PreflightError(
                f"Runtime {host.runtime_type} is not available on {host.name}: {detection.details.get('reason', '')}"
            )
        preflight = PreflightService().run(application, version, host, remote=False)
        failed = [
            c
            for c in preflight.checks
            if c.status == "FAIL"
            and c.name not in {"conflicts", "parallel_limit", "existing_state"}
        ]
        deployment.preflight_result = preflight.to_dict()
        if failed:
            raise PreflightError("; ".join(f"{c.label}: {c.message}" for c in failed))
        ctx.log(
            "INFO",
            f"Pre-flight passed ({len(preflight.checks)} checks, runtime {detection.version})",
        )
        return {"runtime_version": detection.version, "checks": [c.name for c in preflight.checks]}

    def _step_prepare(
        self,
        step,
        ctx,
        adapter,
        deployment,
        application,
        version,
        host,
        environment,
        desired,
        instance,
        state,
        execution,
    ):
        fs = FileCommands(ctx.layout.base_path)
        for directory in ctx.layout.all_dirs():
            ctx.run(fs.mkdir(directory), label=f"mkdir {directory}")
        for volume in desired.manifest.get("volumes") or []:
            shared_dir = {
                "data": ctx.layout.shared_data_dir,
                "config": ctx.layout.shared_config_dir,
                "logs": ctx.layout.shared_logs_dir,
            }[volume.get("shared", "data")]
            ctx.run(
                fs.mkdir(f"{shared_dir}/{volume['name']}"), label=f"mkdir volume {volume['name']}"
            )
        return {"layout": ctx.layout.app_dir}

    def _step_transfer(
        self,
        step,
        ctx,
        adapter,
        deployment,
        application,
        version,
        host,
        environment,
        desired,
        instance,
        state,
        execution,
    ):
        fs = FileCommands(ctx.layout.base_path)
        release_dir = ctx.layout.release_dir(version.version)
        if (
            step.params.get("reuse_existing")
            and ctx.run(fs.is_dir(release_dir), label="Check existing release").ok
        ):
            ctx.log("INFO", f"Release {version.version} already present on host; transfer skipped")
            state["reused_release"] = True
            return {"skipped": True, "release_dir": release_dir}
        staging = ctx.layout.staging_package(version.version, state["token"])
        local_path = state["local_path"]
        size = os.path.getsize(local_path)
        t0 = time.monotonic()
        ctx.executor.upload(local_path, staging)
        ctx.log("INFO", f"Transferred {size} bytes to {staging} in {time.monotonic() - t0:.1f}s")
        state["staging_package"] = staging
        return {
            "remote_path": staging,
            "size_bytes": size,
            "seconds": round(time.monotonic() - t0, 2),
        }

    def _step_verify_checksum(
        self,
        step,
        ctx,
        adapter,
        deployment,
        application,
        version,
        host,
        environment,
        desired,
        instance,
        state,
        execution,
    ):
        if state.get("reused_release"):
            return {"skipped": True}
        fs = FileCommands(ctx.layout.base_path)
        result = ctx.run(fs.sha256(state["staging_package"]), label="Remote sha256sum")
        remote = result.stdout.split()[0].strip() if result.stdout.strip() else ""
        if remote != version.checksum_sha256:
            ctx.run(fs.remove_file(state["staging_package"]), label="Remove corrupt upload")
            raise FileTransferError(
                "Remote checksum does not match local checksum; transfer corrupted.",
                details={"remote": remote, "local": version.checksum_sha256},
            )
        ctx.log("INFO", "Remote checksum verified")
        return {"checksum": remote}

    def _step_extract(
        self,
        step,
        ctx,
        adapter,
        deployment,
        application,
        version,
        host,
        environment,
        desired,
        instance,
        state,
        execution,
    ):
        fs = FileCommands(ctx.layout.base_path)
        release_dir = ctx.layout.release_dir(version.version)
        if state.get("reused_release"):
            return {"skipped": True, "release_dir": release_dir}
        tmp_dir = ctx.layout.release_tmp_dir(version.version, state["token"])
        ctx.run(fs.mkdir(tmp_dir), label="Create extraction directory")
        ctx.run(fs.extract_tar(state["staging_package"], tmp_dir), label="Extract package")
        manifest = ctx.run(fs.cat(f"{tmp_dir}/manifest.yaml"), label="Read extracted manifest")
        if not manifest.ok or f"version: {version.version}" not in manifest.stdout.replace(
            "'", ""
        ).replace('"', ""):
            ctx.run(fs.remove_tree(tmp_dir), label="Remove invalid extraction")
            raise DeploymentError("Extracted manifest does not match the release version.")
        if ctx.run(fs.is_dir(release_dir), label="Check release dir").ok:
            # a previous failed attempt left a directory: move it away, never overwrite in place
            backup = f"{ctx.layout.backups_dir}/{version.version}.{state['token']}.old"
            ctx.run(fs.move(release_dir, backup), label="Preserve existing release directory")
        for script in (
            (desired.manifest.get("hooks") or {}).get("pre_deploy", [])
            + (desired.manifest.get("hooks") or {}).get("migrate", [])
            + (desired.manifest.get("hooks") or {}).get("post_deploy", [])
            + (desired.manifest.get("hooks") or {}).get("pre_rollback", [])
            + (desired.manifest.get("hooks") or {}).get("post_rollback", [])
        ):
            ctx.run(fs.chmod_exec(f"{tmp_dir}/{script}"), label=f"chmod {script}")
        ctx.run(fs.move(tmp_dir, release_dir), label="Move release into place")
        ctx.log("INFO", f"Release extracted to {release_dir}")
        return {"release_dir": release_dir}

    def _step_configure(
        self,
        step,
        ctx,
        adapter,
        deployment,
        application,
        version,
        host,
        environment,
        desired,
        instance,
        state,
        execution,
    ):
        env = dict(desired.environment)
        release_dir = ctx.layout.release_dir(version.version)
        env.update(
            {
                "SCARLET_APPLICATION": application.code,
                "SCARLET_VERSION": version.version,
                "SCARLET_ENVIRONMENT": environment.code,
                "SCARLET_RELEASE_DIR": release_dir,
                "SCARLET_SHARED_DIR": ctx.layout.shared_dir,
                "SCARLET_DEPLOYMENT": deployment.reference,
            }
        )
        content = ConfigurationService.render_env_file(env)
        fd, tmp = tempfile.mkstemp(prefix="scarlet-env-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(content)
            ctx.executor.upload(tmp, ctx.layout.env_file)
        finally:
            os.unlink(tmp)
        ctx.log(
            "INFO",
            f"Rendered {len(env)} environment variable(s) to {ctx.layout.env_file} (values not logged)",
        )
        state["release_dir"] = release_dir
        return {"keys": sorted(env.keys()), "env_file": ctx.layout.env_file}

    def _step_hook(
        self,
        step,
        ctx,
        adapter,
        deployment,
        application,
        version,
        host,
        environment,
        desired,
        instance,
        state,
        execution,
    ):
        if not application.allow_hooks:
            raise DeploymentError("Hooks are not enabled for this application.")
        fs = FileCommands(ctx.layout.base_path)
        release_dir = ctx.layout.release_dir(version.version)
        env = {
            "SCARLET_APPLICATION": application.code,
            "SCARLET_VERSION": version.version,
            "SCARLET_ENVIRONMENT": environment.code,
            "SCARLET_RELEASE_DIR": release_dir,
            "SCARLET_SHARED_DIR": ctx.layout.shared_dir,
            "SCARLET_ENV_FILE": ctx.layout.env_file,
            "SCARLET_HOOK": step.params["hook"],
        }
        outputs = []
        for script in step.params["scripts"]:
            result = ctx.run(
                fs.run_hook(
                    f"{release_dir}/{script}",
                    release_dir,
                    int(step.params.get("timeout", 300)),
                    env,
                ),
                label=f"hook {script}",
            )
            outputs.append({"script": script, "exit_code": result.exit_code})
        return {"hook": step.params["hook"], "scripts": outputs}

    def _step_install(
        self,
        step,
        ctx,
        adapter,
        deployment,
        application,
        version,
        host,
        environment,
        desired,
        instance,
        state,
        execution,
    ):
        release_dir = ctx.layout.release_dir(version.version)
        result = adapter.install(ctx, desired, release_dir)
        ctx.log("INFO", f"Install completed: {result}")
        return result

    def _step_activate(
        self,
        step,
        ctx,
        adapter,
        deployment,
        application,
        version,
        host,
        environment,
        desired,
        instance,
        state,
        execution,
    ):
        fs = FileCommands(ctx.layout.base_path)
        release_dir = ctx.layout.release_dir(version.version)
        current = ctx.run(fs.readlink(ctx.layout.current_link), label="Read current symlink")
        state["previous_release_dir"] = (
            current.stdout.strip() if current.ok and current.stdout.strip() else None
        )
        for command in fs.atomic_symlink_switch(release_dir, ctx.layout.current_link):
            ctx.run(command, label=command.description)
        state["activated"] = True
        ctx.log("INFO", f"current -> {release_dir}")
        return {"current": release_dir, "previous": state["previous_release_dir"]}

    def _step_start(
        self,
        step,
        ctx,
        adapter,
        deployment,
        application,
        version,
        host,
        environment,
        desired,
        instance,
        state,
        execution,
    ):
        actual = adapter.start(ctx, desired)
        state["actual"] = actual
        if actual.state not in {ApplicationState.RUNNING, ApplicationState.STARTING}:
            raise DeploymentError(
                f"Application did not start (state {actual.state.value}): {actual.message}",
                details=actual.details,
            )
        ctx.log(
            "INFO",
            f"Started: state={actual.state.value} version={actual.version} ({actual.message or 'ok'})",
        )
        self._update_actual(instance, actual, version)
        return actual.to_dict()

    def _step_health(
        self,
        step,
        ctx,
        adapter,
        deployment,
        application,
        version,
        host,
        environment,
        desired,
        instance,
        state,
        execution,
    ):
        spec = desired.health
        checker = HealthChecker(adapter, sleep=self._sleep)
        result = checker.check(ctx, spec, desired)
        record = HealthCheck(
            instance_id=instance.id,
            check_type=spec.check_type,
            status=result.status.value,
            checked_at=utcnow(),
            duration_seconds=result.duration_seconds,
            attempts=result.attempts,
            message=result.message[:2000],
            details=result.details,
            deployment_id=deployment.id,
        )
        db.session.add(record)
        instance.health_status = result.status.value
        instance.last_health_check_at = utcnow()
        instance.last_health_message = result.message[:2000]
        db.session.commit()
        if not result.healthy:
            raise HealthCheckError(
                f"Health check failed after {result.attempts} attempt(s): {result.message}",
                details=result.details,
            )
        return result.to_dict()

    def _step_finalize(
        self,
        step,
        ctx,
        adapter,
        deployment,
        application,
        version,
        host,
        environment,
        desired,
        instance,
        state,
        execution,
    ):
        actual = adapter.status(ctx)
        execution.actual = actual
        if (
            deployment.kind == DeploymentKind.DEPLOY.value
            and instance.current_version_id
            and instance.current_version_id != version.id
        ):
            instance.previous_version_id = instance.current_version_id
        elif deployment.kind == DeploymentKind.ROLLBACK.value and deployment.rollback_of_id:
            rolled = db.session.get(Deployment, deployment.rollback_of_id)
            if rolled is not None and rolled.version_id != version.id:
                instance.previous_version_id = rolled.version_id
        instance.current_version_id = version.id
        instance.actual_version = version.version
        instance.actual_state = (
            actual.state.value
            if actual.state != ApplicationState.UNKNOWN
            else ApplicationState.RUNNING.value
        )
        instance.actual_runtime = host.runtime_type
        instance.actual_replicas = actual.replicas
        instance.actual_details = actual.details
        instance.actual_observed_at = utcnow()
        instance.drift_detected = False
        instance.drift_type = "NONE"
        instance.drift_details = None
        instance.last_operation_at = utcnow()
        db.session.commit()
        ctx.log(
            "INFO",
            f"{application.code} {version.version} is {instance.actual_state} on {host.name}",
        )
        return {
            "current_version": version.version,
            "previous_version": (
                instance.previous_version.version if instance.previous_version else None
            ),
        }

    def _step_cleanup(
        self,
        step,
        ctx,
        adapter,
        deployment,
        application,
        version,
        host,
        environment,
        desired,
        instance,
        state,
        execution,
    ):
        fs = FileCommands(ctx.layout.base_path)
        removed = []
        if state.get("staging_package"):
            ctx.run(fs.remove_file(state["staging_package"]), label="Remove staged package")
            removed.append(state["staging_package"])
        return {"removed": removed}

    # --- failure handling ---------------------------------------------------------------------------------------
    def _handle_failure(
        self,
        sm,
        deployment,
        failed_step: StepExecution,
        error: ScarletError,
        ctx,
        adapter,
        application,
        host,
        instance,
        state,
        execution,
        step_rows,
    ) -> None:
        instance.last_operation_at = utcnow()
        previous_health = instance.health_status
        try:
            actual = adapter.status(ctx)
            self._update_actual(instance, actual, None)
        except ScarletError:
            instance.actual_state = ApplicationState.UNKNOWN.value
        if failed_step.step.kind == "health":
            instance.health_status = (
                previous_health  # keep the failed probe result, not the runtime's own view
            )
        db.session.commit()
        notify_operators(
            "DEPLOYMENT_FAILED",
            f"Deployment {deployment.reference} failed",
            f"{application.code} {deployment.version.version} on {host.name}: {error.message}",
            level=NotificationLevel.ERROR,
            link=f"/deployments/{deployment.id}",
            email=True,
        )
        should_rollback = (
            deployment.auto_rollback
            and state.get("activated")
            and state.get("previous_version")
            and failed_step.step.rollback_trigger
            and deployment.kind == DeploymentKind.DEPLOY.value
        )
        if not should_rollback:
            if (
                state.get("activated")
                and deployment.kind == DeploymentKind.DEPLOY.value
                and state.get("previous_version")
            ):
                sm.deployment.status = DeploymentStatus.ROLLBACK_REQUIRED.value
                db.session.commit()
            return
        sm.deployment.status = DeploymentStatus.ROLLBACK_REQUIRED.value
        db.session.commit()
        sm.transition(DeploymentStatus.ROLLING_BACK)
        db.session.commit()
        audit.record(
            "ROLLBACK_STARTED",
            entity_type="Deployment",
            entity_id=deployment.id,
            application=application,
            target=host,
            details={"automatic": True, "to_version": state["previous_version"]},
        )
        previous = self.versions.by_app_and_version(application.id, state["previous_version"])
        row = DeploymentStep(
            deployment_id=deployment.id,
            sequence=len(step_rows) + 1,
            name="auto_rollback",
            label=f"Automatic rollback to {state['previous_version']}",
            status=StepStatus.RUNNING.value,
            started_at=utcnow(),
        )
        db.session.add(row)
        db.session.commit()
        logger = ctx.log
        logger.reset()
        try:
            if previous is None:
                raise DeploymentError("Previous version record not found.")
            env_vars, _ = self.config.render_environment(
                application, deployment.environment, previous.manifest or {}
            )
            prev_desired = build_desired_state(application, previous, host, env_vars)
            fs = FileCommands(ctx.layout.base_path)
            prev_release = ctx.layout.release_dir(previous.version)
            if not ctx.run(fs.is_dir(prev_release), label="Check previous release").ok:
                raise DeploymentError(
                    f"Previous release directory {prev_release} is missing on the host."
                )
            for command in fs.atomic_symlink_switch(prev_release, ctx.layout.current_link):
                ctx.run(command, label=command.description)
            actual = adapter.rollback(ctx, prev_desired, prev_release)
            checker = HealthChecker(adapter, sleep=self._sleep)
            health = checker.check(ctx, prev_desired.health, prev_desired)
            instance.current_version_id = previous.id
            instance.actual_version = previous.version
            instance.desired_version_id = previous.id
            instance.health_status = health.status.value
            self._update_actual(instance, actual, previous)
            row.status = StepStatus.SUCCESS.value
            sm.transition(DeploymentStatus.ROLLED_BACK)
            execution.rolled_back = True
            audit.record(
                "ROLLBACK_COMPLETED",
                entity_type="Deployment",
                entity_id=deployment.id,
                application=application,
                target=host,
                details={
                    "automatic": True,
                    "to_version": previous.version,
                    "health": health.status.value,
                },
            )
            notify_operators(
                "ROLLBACK_COMPLETED",
                f"Automatic rollback for {deployment.reference}",
                f"{application.code} rolled back to {previous.version} on {host.name} (health {health.status.value}).",
                level=NotificationLevel.WARNING,
                link=f"/deployments/{deployment.id}",
            )
        except ScarletError as exc:
            row.status = StepStatus.FAILED.value
            row.error_message = redact(exc.message)[:4000]
            sm.deployment.status = DeploymentStatus.FAILED.value
            sm.deployment.error_message = (
                f"{deployment.error_message} | automatic rollback failed: {exc.message}"[:4000]
            )
            audit.record(
                "ROLLBACK_COMPLETED",
                result=AuditResult.FAILURE,
                entity_type="Deployment",
                entity_id=deployment.id,
                application=application,
                target=host,
                details={"automatic": True, "error": exc.message},
            )
        finally:
            row.completed_at = utcnow()
            row.duration_seconds = duration_seconds(row.started_at, row.completed_at)
            row.stdout = logger.stdout_text()
            row.stderr = logger.stderr_text()
            db.session.commit()

    # --- helpers ----------------------------------------------------------------------------------------------------------
    @staticmethod
    def _update_actual(instance, actual: ActualApplicationState, version) -> None:
        instance.actual_state = actual.state.value
        instance.actual_version = actual.version or (
            version.version if version else instance.actual_version
        )
        instance.actual_replicas = actual.replicas
        instance.actual_runtime = actual.runtime
        instance.actual_details = actual.details
        instance.actual_observed_at = utcnow()
        if actual.health != HealthStatus.UNKNOWN:
            instance.health_status = actual.health.value

    @staticmethod
    def _audit_result(deployment, *, success: bool, error: str | None = None) -> None:
        action = "DEPLOYMENT_COMPLETED" if success else "DEPLOYMENT_FAILED"
        if deployment.kind == DeploymentKind.ROLLBACK.value:
            action = "ROLLBACK_COMPLETED" if success else "ROLLBACK_FAILED"
        audit.record(
            action,
            user=deployment.requested_by,
            entity_type="Deployment",
            entity_id=deployment.id,
            application=deployment.application,
            target=deployment.target,
            result=AuditResult.SUCCESS if success else AuditResult.FAILURE,
            details={
                "reference": deployment.reference,
                "version": deployment.version.version,
                "status": deployment.status,
                "error": error,
                "duration_seconds": deployment.duration_seconds,
            },
        )
        if success:
            notify_operators(
                "DEPLOYMENT_SUCCESS",
                f"{deployment.application.code} {deployment.version.version} deployed",
                f"Deployment {deployment.reference} to {deployment.target.name} ({deployment.environment.code}) succeeded.",
                level=NotificationLevel.SUCCESS,
                link=f"/deployments/{deployment.id}",
            )
