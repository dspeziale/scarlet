"""Deployment planner: desired state + target -> ordered DeploymentPlan.

The planner is runtime-agnostic. It only knows the *kinds* of steps the
engine can execute; the runtime adapter decides how each kind is realised.
"""

from __future__ import annotations

from typing import Any

from app.deployment.domain import DeploymentPlan, DesiredApplicationState, HealthSpec, PlanStep
from app.lifecycle.health import health_spec_from_application
from app.models.enums import DesiredState, RuntimeType


def build_desired_state(
    application, version, host, environment_vars: dict[str, str]
) -> DesiredApplicationState:
    manifest: dict[str, Any] = dict(version.manifest or {})
    image = manifest.get("image") or {}
    ports: list[str] = []
    for port in manifest.get("ports") or []:
        host_port = port.get("host") or port.get("container")
        prefix = f"{port['bind']}:" if port.get("bind") else ""
        suffix = "/udp" if port.get("protocol") == "udp" else ""
        ports.append(f"{prefix}{host_port}:{port['container']}{suffix}")
    from flask import current_app

    from app.deployment.remote_layout import RemoteLayout

    base = host.remote_base_path or current_app.config["SCARLET_REMOTE_BASE_PATH"]
    layout = RemoteLayout(base, application.code)
    volumes: list[str] = []
    for volume in manifest.get("volumes") or []:
        shared_dir = {
            "data": layout.shared_data_dir,
            "config": layout.shared_config_dir,
            "logs": layout.shared_logs_dir,
        }[volume.get("shared", "data")]
        source = f"{shared_dir}/{volume['name']}"
        volumes.append(f"{source}:{volume['mount']}" + (":ro" if volume.get("read_only") else ""))
    health = health_spec_from_application(application, manifest)
    deployment_spec = manifest.get("deployment") or {}
    k8s = manifest.get("kubernetes") or {}
    return DesiredApplicationState(
        application_code=application.code,
        version=version.version,
        state=DesiredState.RUNNING,
        replicas=int(deployment_spec.get("replicas") or 1) or 1,
        image=f"{image['name']}:{image['tag']}" if image else None,
        manifest=manifest,
        environment=environment_vars,
        health=health,
        ports=tuple(ports),
        volumes=tuple(volumes),
        resources=dict(manifest.get("resources") or {}),
        namespace=k8s.get("namespace") or host.kubernetes_namespace,
    )


class DeploymentPlanner:
    def plan(
        self,
        *,
        reference: str,
        application,
        version,
        host,
        desired: DesiredApplicationState,
        previous_version: str | None,
        kind: str = "DEPLOY",
        auto_rollback: bool = False,
    ) -> DeploymentPlan:
        manifest = desired.manifest
        hooks = manifest.get("hooks") or {}
        is_rollback = kind == "ROLLBACK"
        is_k8s = host.runtime_type == RuntimeType.KUBERNETES.value
        steps: list[PlanStep] = [
            PlanStep(
                "validate", "Validate package", "validate", {"checksum": version.checksum_sha256}
            ),
            PlanStep("preflight", "Check target", "preflight", {"remote": True}),
            PlanStep("prepare", "Prepare remote layout", "prepare"),
            PlanStep("transfer", "Transfer package", "transfer", {"reuse_existing": is_rollback}),
            PlanStep(
                "verify",
                "Verify checksum",
                "verify_checksum",
                {"checksum": version.checksum_sha256, "reuse_existing": is_rollback},
            ),
            PlanStep("extract", "Extract release", "extract", {"reuse_existing": is_rollback}),
            PlanStep("configure", "Render configuration", "configure"),
        ]
        hook_key = "pre_rollback" if is_rollback else "pre_deploy"
        if application.allow_hooks and hooks.get(hook_key):
            steps.append(
                PlanStep(
                    f"hook_{hook_key}",
                    f"Run {hook_key.replace('_', '-')} hooks",
                    "hook",
                    {
                        "hook": hook_key,
                        "scripts": hooks[hook_key],
                        "timeout": hooks.get("timeout", 300),
                    },
                )
            )
        if application.allow_hooks and hooks.get("migrate") and not is_rollback:
            steps.append(
                PlanStep(
                    "hook_migrate",
                    "Run migration hooks",
                    "hook",
                    {
                        "hook": "migrate",
                        "scripts": hooks["migrate"],
                        "timeout": hooks.get("timeout", 300),
                    },
                )
            )
        steps.append(
            PlanStep(
                "install",
                "Install release" if not is_k8s else "Apply Kubernetes objects",
                "install",
                {"image": desired.image},
            )
        )
        steps.append(
            PlanStep(
                "activate", "Activate release (switch current)", "activate", rollback_trigger=True
            )
        )
        steps.append(
            PlanStep(
                "start",
                "Start application",
                "start",
                {"replicas": desired.replicas},
                rollback_trigger=True,
            )
        )
        steps.append(
            PlanStep(
                "health", "Health check", "health", desired.health.to_dict(), rollback_trigger=True
            )
        )
        post_key = "post_rollback" if is_rollback else "post_deploy"
        if application.allow_hooks and hooks.get(post_key):
            steps.append(
                PlanStep(
                    f"hook_{post_key}",
                    f"Run {post_key.replace('_', '-')} hooks",
                    "hook",
                    {
                        "hook": post_key,
                        "scripts": hooks[post_key],
                        "timeout": hooks.get("timeout", 300),
                    },
                    critical=False,
                )
            )
        steps.append(PlanStep("finalize", "Finalize", "finalize"))
        steps.append(PlanStep("cleanup", "Clean staging", "cleanup", critical=False))
        return DeploymentPlan(
            reference=reference,
            application_code=application.code,
            target_name=host.name,
            runtime_type=host.runtime_type,
            desired=desired,
            previous_version=previous_version,
            steps=steps,
            strategy=str((manifest.get("deployment") or {}).get("strategy", "recreate")).upper(),
            auto_rollback=auto_rollback and previous_version is not None,
        )

    @staticmethod
    def health_from_plan(plan_step: PlanStep) -> HealthSpec:
        params = dict(plan_step.params)
        params["command"] = tuple(params.get("command") or ())
        return HealthSpec(**params)
