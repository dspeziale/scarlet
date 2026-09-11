"""Kubernetes runtime adapter.

Two access modes:

* **API mode** (preferred): the target has a ``KUBECONFIG`` credential. SCARLET
  talks to the cluster with the official Python client and applies the YAML
  manifests shipped inside the release package (read from local artifact
  storage). The remote host is still used to keep the release directory layout
  and the ``current`` symlink, so version history and rollback work uniformly.
* **kubectl mode**: no kubeconfig credential; ``kubectl`` is executed on the
  target host over SSH against the release directory.

Supported objects: Namespace, Deployment, Service, ConfigMap, Secret (from the
package). The Deployment named in the manifest is the unit of status/scale/
logs/rollback.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import yaml

from app.deployment.domain import ActualApplicationState, DesiredApplicationState, HealthSpec
from app.errors import RuntimeOperationError, ValidationError
from app.models.enums import ApplicationState, HealthStatus, RuntimeType
from app.runtimes.base import (
    HealthResult,
    LogChunk,
    RuntimeAdapter,
    RuntimeContext,
    RuntimeDetection,
)
from app.security.validators import validate_int_range, validate_k8s_name
from app.ssh.command import RemoteCommand, SystemCommands, validate_remote_path

SUPPORTED_KINDS = {"Namespace", "Deployment", "Service", "ConfigMap", "Secret"}


class KubernetesRuntimeAdapter(RuntimeAdapter):
    runtime_type = RuntimeType.KUBERNETES
    supports_scaling = True

    # --- common helpers ----------------------------------------------------------------
    def _namespace(
        self, ctx: RuntimeContext, desired: DesiredApplicationState | None = None
    ) -> str:
        ns = (desired.namespace if desired else None) or ctx.host.kubernetes_namespace or "default"
        return validate_k8s_name(ns, field="namespace")

    def _deployment_name(
        self, ctx: RuntimeContext, desired: DesiredApplicationState | None = None
    ) -> str:
        k8s = (desired.manifest.get("kubernetes") if desired else None) or {}
        return validate_k8s_name(
            k8s.get("deployment_name") or ctx.application_code, field="deployment_name"
        )

    def _api_mode(self, ctx: RuntimeContext) -> bool:
        return bool(ctx.host.kubeconfig)

    def _kubectl(
        self,
        ctx: RuntimeContext,
        *args: str,
        command_type: str,
        description: str,
        allow_failure: bool = False,
        timeout: int | None = None,
    ) -> RemoteCommand:
        argv: list[str] = ["kubectl"]
        if ctx.host.kubernetes_context:
            argv += ["--context", validate_k8s_name(ctx.host.kubernetes_context, field="context")]
        argv += list(args)
        return RemoteCommand(
            tuple(argv),
            f"runtime.kubernetes.{command_type}",
            description,
            allow_failure=allow_failure,
            timeout=timeout or ctx.timeout,
        )

    # --- API client ---------------------------------------------------------------------
    def _clients(self, ctx: RuntimeContext):
        from kubernetes import client as k8s_client
        from kubernetes import config as k8s_config

        loader_cfg = yaml.safe_load(ctx.host.kubeconfig or "") or {}
        configuration = k8s_client.Configuration()
        k8s_config.load_kube_config_from_dict(
            loader_cfg,
            context=ctx.host.kubernetes_context or None,
            client_configuration=configuration,
        )
        api_client = k8s_client.ApiClient(configuration)
        return (
            k8s_client.CoreV1Api(api_client),
            k8s_client.AppsV1Api(api_client),
            k8s_client.VersionApi(api_client),
        )

    def _local_manifest_docs(
        self, ctx: RuntimeContext, desired: DesiredApplicationState
    ) -> list[dict[str, Any]]:
        local_dir = getattr(ctx, "local_release_dir", None) or desired.manifest.get(
            "_local_release_dir"
        )
        k8s = desired.manifest.get("kubernetes") or {}
        manifests_dir = k8s.get("manifests")
        if not local_dir or not manifests_dir:
            raise RuntimeOperationError(
                "Kubernetes manifests are not available locally for API mode."
            )
        root = Path(local_dir).resolve()
        directory = (root / manifests_dir).resolve()
        if root not in directory.parents and directory != root:
            raise RuntimeOperationError("Manifest directory escapes the release directory.")
        docs: list[dict[str, Any]] = []
        for path in sorted(directory.rglob("*")):
            if path.suffix.lower() not in {".yml", ".yaml"} or not path.is_file():
                continue
            for doc in yaml.safe_load_all(path.read_text(encoding="utf-8")):
                if not isinstance(doc, dict) or not doc.get("kind"):
                    continue
                kind = doc["kind"]
                if kind not in SUPPORTED_KINDS:
                    raise RuntimeOperationError(
                        f"Unsupported Kubernetes object kind '{kind}' in {path.name}."
                    )
                docs.append(doc)
        if not docs:
            raise RuntimeOperationError("No Kubernetes manifests found in the release package.")
        return docs

    def _apply_docs(
        self, ctx: RuntimeContext, docs: list[dict[str, Any]], namespace: str
    ) -> list[str]:
        from kubernetes.client.exceptions import ApiException

        core, apps, _ = self._clients(ctx)
        applied: list[str] = []
        for doc in docs:
            kind = doc["kind"]
            meta = doc.setdefault("metadata", {})
            name = validate_k8s_name(meta.get("name", ""), field="metadata.name")
            if kind != "Namespace":
                meta["namespace"] = namespace
            labels = meta.setdefault("labels", {})
            labels["scarlet.io/application"] = ctx.application_code
            labels["app.kubernetes.io/managed-by"] = "scarlet"
            try:
                if kind == "Namespace":
                    try:
                        core.read_namespace(name)
                    except ApiException as exc:
                        if exc.status != 404:
                            raise
                        core.create_namespace(doc)
                elif kind == "Deployment":
                    try:
                        apps.read_namespaced_deployment(name, namespace)
                        apps.patch_namespaced_deployment(name, namespace, doc)
                    except ApiException as exc:
                        if exc.status != 404:
                            raise
                        apps.create_namespaced_deployment(namespace, doc)
                elif kind == "Service":
                    try:
                        core.read_namespaced_service(name, namespace)
                        core.patch_namespaced_service(name, namespace, doc)
                    except ApiException as exc:
                        if exc.status != 404:
                            raise
                        core.create_namespaced_service(namespace, doc)
                elif kind == "ConfigMap":
                    try:
                        core.read_namespaced_config_map(name, namespace)
                        core.replace_namespaced_config_map(name, namespace, doc)
                    except ApiException as exc:
                        if exc.status != 404:
                            raise
                        core.create_namespaced_config_map(namespace, doc)
                elif kind == "Secret":
                    try:
                        core.read_namespaced_secret(name, namespace)
                        core.replace_namespaced_secret(name, namespace, doc)
                    except ApiException as exc:
                        if exc.status != 404:
                            raise
                        core.create_namespaced_secret(namespace, doc)
            except ApiException as exc:
                raise RuntimeOperationError(
                    f"Kubernetes API error applying {kind}/{name}: {exc.status} {exc.reason}"
                ) from exc
            applied.append(f"{kind}/{name}")
            ctx.log("INFO", f"Applied {kind}/{name} in namespace {namespace}")
        return applied

    # --- detection --------------------------------------------------------------------------
    def detect(self, ctx: RuntimeContext) -> RuntimeDetection:
        if self._api_mode(ctx):
            try:
                _, _, version_api = self._clients(ctx)
                info = version_api.get_code()
                return RuntimeDetection(
                    self.runtime_type.value,
                    True,
                    version=getattr(info, "git_version", None),
                    details={"mode": "api", "platform": getattr(info, "platform", None)},
                )
            except Exception as exc:  # noqa: BLE001
                return RuntimeDetection(
                    self.runtime_type.value,
                    False,
                    details={"mode": "api", "reason": str(exc)[:300]},
                )
        which = ctx.run(SystemCommands.which("kubectl"), label="Locate kubectl")
        if not which.ok:
            return RuntimeDetection(
                self.runtime_type.value,
                False,
                details={"mode": "kubectl", "reason": "kubectl not found"},
            )
        version = ctx.run(SystemCommands.kubectl_version(), label="kubectl version")
        details: dict[str, Any] = {"mode": "kubectl"}
        server_version = None
        if version.stdout.strip():
            try:
                data = json.loads(version.stdout)
                details["client_version"] = (data.get("clientVersion") or {}).get("gitVersion")
                server_version = (data.get("serverVersion") or {}).get("gitVersion")
            except json.JSONDecodeError:
                pass
        return RuntimeDetection(
            self.runtime_type.value,
            available=server_version is not None,
            version=server_version,
            binary_path=which.stdout.strip() or None,
            details=details,
        )

    # --- observation -------------------------------------------------------------------------
    def _read_deployment(
        self, ctx: RuntimeContext, desired: DesiredApplicationState | None = None
    ) -> dict[str, Any] | None:
        namespace = self._namespace(ctx, desired)
        name = self._deployment_name(ctx, desired)
        if self._api_mode(ctx):
            from kubernetes.client.exceptions import ApiException

            _, apps, _ = self._clients(ctx)
            try:
                obj = apps.read_namespaced_deployment(name, namespace)
            except ApiException as exc:
                if exc.status == 404:
                    return None
                raise RuntimeOperationError(
                    f"Kubernetes API error: {exc.status} {exc.reason}"
                ) from exc
            return apps.api_client.sanitize_for_serialization(obj)
        result = ctx.run(
            self._kubectl(
                ctx,
                "get",
                "deployment",
                name,
                "-n",
                namespace,
                "-o",
                "json",
                command_type="get",
                description="Get deployment",
                allow_failure=True,
                timeout=60,
            ),
            label="Get deployment",
        )
        if not result.ok:
            return None
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            return None

    def status(self, ctx: RuntimeContext) -> ActualApplicationState:
        actual = ActualApplicationState(
            application_code=ctx.application_code, runtime=self.runtime_type.value
        )
        data = self._read_deployment(ctx)
        if data is None:
            actual.state = ApplicationState.NOT_INSTALLED
            actual.message = "Deployment not found in namespace."
            return actual
        spec = data.get("spec") or {}
        status = data.get("status") or {}
        labels = (data.get("metadata") or {}).get("labels") or {}
        desired_replicas = int(spec.get("replicas") or 0)
        ready = int(status.get("readyReplicas") or 0)
        available = int(status.get("availableReplicas") or 0)
        actual.replicas = ready
        actual.version = labels.get("scarlet.io/version") or (
            (spec.get("template") or {}).get("metadata") or {}
        ).get("labels", {}).get("scarlet.io/version")
        containers = ((spec.get("template") or {}).get("spec") or {}).get("containers") or []
        if containers:
            actual.image = containers[0].get("image")
        if desired_replicas == 0:
            actual.state = ApplicationState.STOPPED
        elif ready >= desired_replicas:
            actual.state = ApplicationState.RUNNING
            actual.health = HealthStatus.HEALTHY
        elif ready == 0 and any(
            (c.get("type") == "Progressing" and c.get("status") == "False")
            for c in status.get("conditions") or []
        ):
            actual.state = ApplicationState.FAILED
            actual.health = HealthStatus.UNHEALTHY
        else:
            actual.state = ApplicationState.STARTING
        actual.details = {
            "namespace": self._namespace(ctx),
            "deployment": self._deployment_name(ctx),
            "desired_replicas": desired_replicas,
            "ready_replicas": ready,
            "available_replicas": available,
            "updated_replicas": status.get("updatedReplicas"),
            "generation": data.get("metadata", {}).get("generation"),
            "observed_generation": status.get("observedGeneration"),
            "conditions": [
                {"type": c.get("type"), "status": c.get("status"), "reason": c.get("reason")}
                for c in status.get("conditions") or []
            ],
        }
        return actual

    def version(self, ctx: RuntimeContext) -> str | None:
        return self.status(ctx).version

    def inspect(self, ctx: RuntimeContext) -> dict[str, Any]:
        data = self._read_deployment(ctx) or {}
        spec = data.get("spec") or {}
        template = (spec.get("template") or {}).get("spec") or {}
        containers = []
        for c in template.get("containers") or []:
            containers.append(
                {
                    "name": c.get("name"),
                    "image": c.get("image"),
                    "ports": c.get("ports"),
                    "resources": c.get("resources"),
                }
            )
        return {
            "metadata": {
                k: (data.get("metadata") or {}).get(k)
                for k in ("name", "namespace", "labels", "generation", "creationTimestamp")
            },
            "replicas": spec.get("replicas"),
            "strategy": spec.get("strategy"),
            "containers": containers,
            "status": data.get("status"),
        }

    def logs(self, ctx: RuntimeContext, lines: int = 200, since: str | None = None) -> LogChunk:
        lines = validate_int_range(lines, field="lines", minimum=1, maximum=5000)
        namespace = self._namespace(ctx)
        name = self._deployment_name(ctx)
        if self._api_mode(ctx):
            from kubernetes.client.exceptions import ApiException

            core, _, _ = self._clients(ctx)
            try:
                pods = core.list_namespaced_pod(
                    namespace, label_selector=f"scarlet.io/application={ctx.application_code}"
                )
                out: list[str] = []
                for pod in pods.items[:5]:
                    text = core.read_namespaced_pod_log(
                        pod.metadata.name, namespace, tail_lines=lines, timestamps=True
                    )
                    out.extend(f"[{pod.metadata.name}] {line}" for line in text.splitlines())
            except ApiException as exc:
                raise RuntimeOperationError(
                    f"Unable to read pod logs: {exc.status} {exc.reason}"
                ) from exc
            return LogChunk(
                lines=out[-lines:],
                source=f"kubernetes pods ns={namespace}",
                truncated=len(out) > lines,
            )
        args = [
            "logs",
            f"deployment/{name}",
            "-n",
            namespace,
            "--all-containers=true",
            "--timestamps",
            f"--tail={lines}",
        ]
        if since:
            import re

            if not re.fullmatch(r"\d{1,5}[smh]", since):
                raise ValidationError(
                    "Invalid 'since' value.", errors={"since": ["Use 10m or 2h."]}
                )
            args.append(f"--since={since}")
        result = ctx.run(
            self._kubectl(
                ctx,
                *args,
                command_type="logs",
                description="Collect pod logs",
                allow_failure=True,
                timeout=60,
            ),
            label="Collect logs",
        )
        if not result.ok:
            raise RuntimeOperationError(f"Unable to collect logs: {result.stderr.strip()[:300]}")
        out = [line for line in result.stdout.splitlines() if line.strip()]
        return LogChunk(
            lines=out[-lines:], source=f"kubectl logs deployment/{name}", truncated=len(out) > lines
        )

    def health(
        self, ctx: RuntimeContext, spec: HealthSpec, desired: DesiredApplicationState | None = None
    ) -> HealthResult:
        t0 = time.monotonic()
        actual = self.status(ctx)
        if actual.state == ApplicationState.RUNNING:
            return HealthResult(
                HealthStatus.HEALTHY,
                f"{actual.replicas} ready replica(s)",
                details=actual.details,
                duration_seconds=round(time.monotonic() - t0, 3),
            )
        return HealthResult(
            HealthStatus.UNHEALTHY,
            f"Deployment state is {actual.state.value}",
            details=actual.details,
            duration_seconds=round(time.monotonic() - t0, 3),
        )

    # --- mutation ---------------------------------------------------------------------------------
    def install(
        self, ctx: RuntimeContext, desired: DesiredApplicationState, release_dir: str
    ) -> dict[str, Any]:
        namespace = self._namespace(ctx, desired)
        if self._api_mode(ctx):
            docs = self._local_manifest_docs(ctx, desired)
            for doc in docs:
                if doc.get("kind") == "Deployment":
                    labels = doc.setdefault("metadata", {}).setdefault("labels", {})
                    labels["scarlet.io/version"] = desired.version
                    tmpl = (
                        doc.setdefault("spec", {})
                        .setdefault("template", {})
                        .setdefault("metadata", {})
                        .setdefault("labels", {})
                    )
                    tmpl["scarlet.io/version"] = desired.version
                    tmpl["scarlet.io/application"] = ctx.application_code
            applied = self._apply_docs(ctx, docs, namespace)
            return {"mode": "api", "applied": applied, "namespace": namespace}
        k8s = desired.manifest.get("kubernetes") or {}
        manifests_dir = k8s.get("manifests")
        if not manifests_dir:
            raise RuntimeOperationError(
                "kubectl mode requires kubernetes.manifests in the manifest."
            )
        remote_dir = validate_remote_path(f"{release_dir}/{manifests_dir}", ctx.layout.base_path)
        ctx.run(
            self._kubectl(
                ctx,
                "apply",
                "-n",
                namespace,
                "-f",
                remote_dir,
                command_type="apply",
                description="Apply manifests",
                timeout=300,
            ),
            label="Apply manifests",
        )
        name = self._deployment_name(ctx, desired)
        ctx.run(
            self._kubectl(
                ctx,
                "label",
                "deployment",
                name,
                "-n",
                namespace,
                f"scarlet.io/version={desired.version}",
                f"scarlet.io/application={ctx.application_code}",
                "--overwrite",
                command_type="label",
                description="Label deployment",
                allow_failure=True,
                timeout=60,
            ),
            label="Label deployment",
        )
        return {"mode": "kubectl", "namespace": namespace, "manifests": remote_dir}

    def start(
        self, ctx: RuntimeContext, desired: DesiredApplicationState
    ) -> ActualApplicationState:
        actual = self.status(ctx)
        replicas = max(1, int(desired.replicas or 1))
        if (
            actual.state == ApplicationState.RUNNING
            and actual.version == desired.version
            and (actual.replicas or 0) >= replicas
        ):
            actual.message = "ALREADY_RUNNING"
            return actual
        if actual.state == ApplicationState.NOT_INSTALLED:
            self.install(ctx, desired, ctx.layout.release_dir(desired.version))
        self.scale(ctx, replicas, desired)
        self._wait_rollout(ctx, desired)
        return self.status(ctx)

    def _wait_rollout(self, ctx: RuntimeContext, desired: DesiredApplicationState | None) -> None:
        namespace = self._namespace(ctx, desired)
        name = self._deployment_name(ctx, desired)
        timeout = int(
            ((desired.manifest.get("deployment") or {}).get("start_timeout") if desired else None)
            or 120
        )
        if self._api_mode(ctx):
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                actual = self.status(ctx)
                if actual.state in {ApplicationState.RUNNING, ApplicationState.STOPPED}:
                    return
                if actual.state == ApplicationState.FAILED:
                    raise RuntimeOperationError("Deployment rollout failed.")
                time.sleep(3)
            raise RuntimeOperationError(f"Deployment rollout did not complete within {timeout}s.")
        ctx.run(
            self._kubectl(
                ctx,
                "rollout",
                "status",
                f"deployment/{name}",
                "-n",
                namespace,
                f"--timeout={timeout}s",
                command_type="rollout_status",
                description="Wait for rollout",
                timeout=timeout + 30,
            ),
            label="Wait for rollout",
        )

    def stop(self, ctx: RuntimeContext) -> ActualApplicationState:
        actual = self.status(ctx)
        if actual.state in {ApplicationState.STOPPED, ApplicationState.NOT_INSTALLED}:
            actual.message = "ALREADY_STOPPED"
            return actual
        self.scale(ctx, 0)
        result = self.status(ctx)
        result.message = "STOPPED"
        return result

    def restart(
        self, ctx: RuntimeContext, desired: DesiredApplicationState
    ) -> ActualApplicationState:
        namespace = self._namespace(ctx, desired)
        name = self._deployment_name(ctx, desired)
        if self.status(ctx).state == ApplicationState.NOT_INSTALLED:
            return self.start(ctx, desired)
        if self._api_mode(ctx):
            from datetime import UTC, datetime

            _, apps, _ = self._clients(ctx)
            patch = {
                "spec": {
                    "template": {
                        "metadata": {
                            "annotations": {
                                "kubectl.kubernetes.io/restartedAt": datetime.now(UTC).isoformat()
                            }
                        }
                    }
                }
            }
            apps.patch_namespaced_deployment(name, namespace, patch)
        else:
            ctx.run(
                self._kubectl(
                    ctx,
                    "rollout",
                    "restart",
                    f"deployment/{name}",
                    "-n",
                    namespace,
                    command_type="rollout_restart",
                    description="Rollout restart",
                    timeout=60,
                ),
                label="Rollout restart",
            )
        self._wait_rollout(ctx, desired)
        return self.status(ctx)

    def scale(
        self, ctx: RuntimeContext, replicas: int, desired: DesiredApplicationState | None = None
    ) -> ActualApplicationState:
        replicas = validate_int_range(replicas, field="replicas", minimum=0, maximum=100)
        namespace = self._namespace(ctx, desired)
        name = self._deployment_name(ctx, desired)
        if self._api_mode(ctx):
            from kubernetes.client.exceptions import ApiException

            _, apps, _ = self._clients(ctx)
            try:
                apps.patch_namespaced_deployment_scale(
                    name, namespace, {"spec": {"replicas": replicas}}
                )
            except ApiException as exc:
                raise RuntimeOperationError(
                    f"Unable to scale deployment: {exc.status} {exc.reason}"
                ) from exc
        else:
            ctx.run(
                self._kubectl(
                    ctx,
                    "scale",
                    f"deployment/{name}",
                    "-n",
                    namespace,
                    f"--replicas={replicas}",
                    command_type="scale",
                    description="Scale deployment",
                    timeout=60,
                ),
                label="Scale deployment",
            )
        return self.status(ctx)

    def remove(self, ctx: RuntimeContext) -> None:
        namespace = self._namespace(ctx)
        if self._api_mode(ctx):
            from kubernetes.client.exceptions import ApiException

            core, apps, _ = self._clients(ctx)
            selector = f"scarlet.io/application={ctx.application_code}"
            try:
                apps.delete_collection_namespaced_deployment(namespace, label_selector=selector)
                (
                    core.delete_collection_namespaced_service(namespace, label_selector=selector)
                    if hasattr(core, "delete_collection_namespaced_service")
                    else None
                )
                core.delete_collection_namespaced_config_map(namespace, label_selector=selector)
                core.delete_collection_namespaced_secret(namespace, label_selector=selector)
            except ApiException as exc:
                raise RuntimeOperationError(
                    f"Unable to remove Kubernetes objects: {exc.status} {exc.reason}"
                ) from exc
            return
        ctx.run(
            self._kubectl(
                ctx,
                "delete",
                "deployment,service,configmap,secret",
                "-n",
                namespace,
                "-l",
                f"scarlet.io/application={ctx.application_code}",
                "--ignore-not-found=true",
                command_type="delete",
                description="Delete objects",
                timeout=300,
            ),
            label="Delete objects",
        )

    def rollback(
        self, ctx: RuntimeContext, previous: DesiredApplicationState, release_dir: str
    ) -> ActualApplicationState:
        self.install(ctx, previous, release_dir)
        self.scale(ctx, max(1, previous.replicas or 1), previous)
        self._wait_rollout(ctx, previous)
        return self.status(ctx)
