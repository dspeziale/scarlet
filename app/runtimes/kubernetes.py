"""Kubernetes runtime adapter.

Two access modes, one behaviour:

* **API mode** (a target registered with a kubeconfig): SCARLET talks to the cluster through
  :mod:`app.runtimes.k8s_api` and applies the YAML shipped inside the release package, read
  from the locally extracted artifact. Such a target has no shell and needs no SSH at all.
* **kubectl mode**: no kubeconfig; ``kubectl`` runs on a target host over SSH against the
  release directory, and the usual host layout (releases, ``current`` symlink) applies.

Whatever the mode, SCARLET owns three things in the rendered objects: the image comes from
the released manifest, the configuration and secrets arrive as a Secret wired with
``envFrom``, and every object carries the labels that make the application recognisable
later (``scarlet.io/application``, ``scarlet.io/version``).
"""

from __future__ import annotations

import json
import re
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
from app.runtimes.k8s_api import (
    CLEANUP_KINDS,
    CLUSTER_KINDS,
    SUPPORTED_KINDS,
    KubernetesApi,
    get_kubernetes_api,
)
from app.security.validators import validate_int_range, validate_k8s_name
from app.ssh.command import RemoteCommand, SystemCommands, validate_remote_path

APP_LABEL = "scarlet.io/application"
VERSION_LABEL = "scarlet.io/version"
MANAGED_BY = "app.kubernetes.io/managed-by"
SINCE_PATTERN = re.compile(r"(\d{1,5})([smh])")
SINCE_SECONDS = {"s": 1, "m": 60, "h": 3600}


class KubernetesRuntimeAdapter(RuntimeAdapter):
    runtime_type = RuntimeType.KUBERNETES
    supports_scaling = True
    #: The engine must not write an env file on a host: the Secret is created in the cluster.
    manages_configuration = True

    # --- naming ------------------------------------------------------------------------
    def _namespace(
        self, ctx: RuntimeContext, desired: DesiredApplicationState | None = None
    ) -> str:
        ns = (desired.namespace if desired else None) or ctx.host.kubernetes_namespace or "default"
        return validate_k8s_name(ns, field="namespace")

    def _k8s_manifest(self, desired: DesiredApplicationState | None) -> dict[str, Any]:
        return (desired.manifest.get("kubernetes") if desired else None) or {}

    def _deployment_name(
        self, ctx: RuntimeContext, desired: DesiredApplicationState | None = None
    ) -> str:
        k8s = self._k8s_manifest(desired)
        return validate_k8s_name(
            k8s.get("deployment_name") or ctx.application_code, field="deployment_name"
        )

    def _container_name(
        self, ctx: RuntimeContext, desired: DesiredApplicationState | None = None
    ) -> str:
        k8s = self._k8s_manifest(desired)
        return validate_k8s_name(
            k8s.get("container_name") or ctx.application_code, field="container_name"
        )

    def secret_name(self, ctx: RuntimeContext) -> str:
        """Secret holding the configuration SCARLET renders for the application."""
        return validate_k8s_name(f"{ctx.application_code}-scarlet-env", field="secret_name")

    def _selector(self, ctx: RuntimeContext) -> str:
        return f"{APP_LABEL}={ctx.application_code}"

    # --- access ------------------------------------------------------------------------
    def _api_mode(self, ctx: RuntimeContext) -> bool:
        return bool(ctx.host.kubeconfig)

    def _api(self, ctx: RuntimeContext) -> KubernetesApi:
        """The cluster client, built once per context: one TLS handshake per operation."""
        if ctx.runtime_client is None:
            ctx.runtime_client = get_kubernetes_api(
                ctx.host.kubeconfig or "", ctx.host.kubernetes_context
            )
        return ctx.runtime_client

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

    # --- manifests ---------------------------------------------------------------------
    def _local_manifest_docs(
        self, ctx: RuntimeContext, desired: DesiredApplicationState
    ) -> list[dict[str, Any]]:
        local_dir = getattr(ctx, "local_release_dir", None)
        manifests_dir = self._k8s_manifest(desired).get("manifests")
        if not local_dir or not manifests_dir:
            raise RuntimeOperationError(
                "The Kubernetes objects of the release are not available locally: "
                "the package must declare kubernetes.manifests."
            )
        root = Path(local_dir).resolve()
        directory = (root / manifests_dir).resolve()
        if root != directory and root not in directory.parents:
            raise RuntimeOperationError("The manifest directory escapes the release directory.")
        if not directory.is_dir():
            raise RuntimeOperationError(
                f"Directory '{manifests_dir}' is missing from the release package."
            )
        docs: list[dict[str, Any]] = []
        for path in sorted(directory.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in {".yml", ".yaml"}:
                continue
            for doc in yaml.safe_load_all(path.read_text(encoding="utf-8")):
                if not isinstance(doc, dict) or not doc.get("kind"):
                    continue
                kind = doc["kind"]
                if kind not in SUPPORTED_KINDS:
                    raise RuntimeOperationError(
                        f"Object kind '{kind}' in {path.name} is not among the kinds SCARLET "
                        f"applies. Supported: {', '.join(sorted(SUPPORTED_KINDS))}."
                    )
                docs.append(doc)
        if not docs:
            raise RuntimeOperationError("No Kubernetes objects found in the release package.")
        return docs

    def _decorate(
        self, ctx: RuntimeContext, doc: dict[str, Any], desired: DesiredApplicationState
    ) -> dict[str, Any]:
        """Stamp ownership labels and, on the workload, the image and the configuration."""
        meta = doc.setdefault("metadata", {})
        labels = meta.setdefault("labels", {})
        labels[APP_LABEL] = ctx.application_code
        labels[MANAGED_BY] = "scarlet"
        if doc.get("kind") not in {"Deployment", "StatefulSet", "DaemonSet"}:
            return doc

        labels[VERSION_LABEL] = desired.version
        spec = doc.setdefault("spec", {})
        template = spec.setdefault("template", {})
        tmpl_meta = template.setdefault("metadata", {})
        tmpl_labels = tmpl_meta.setdefault("labels", {})
        tmpl_labels[APP_LABEL] = ctx.application_code
        tmpl_labels[VERSION_LABEL] = desired.version
        if doc["kind"] == "Deployment" and desired.replicas:
            spec["replicas"] = int(desired.replicas)

        pod_spec = template.setdefault("spec", {})
        containers = pod_spec.setdefault("containers", [])
        if not containers:
            raise RuntimeOperationError(f"{doc['kind']}/{meta.get('name')} declares no container.")
        wanted = self._container_name(ctx, desired)
        target = next((c for c in containers if c.get("name") == wanted), containers[0])
        if desired.image:
            target["image"] = desired.image
        env_from = target.setdefault("envFrom", [])
        secret = self.secret_name(ctx)
        if not any((e.get("secretRef") or {}).get("name") == secret for e in env_from):
            env_from.append({"secretRef": {"name": secret, "optional": True}})
        return doc

    # --- detection ---------------------------------------------------------------------
    def detect(self, ctx: RuntimeContext) -> RuntimeDetection:
        if self._api_mode(ctx):
            try:
                info = self._api(ctx).server_version()
            except Exception as exc:  # noqa: BLE001 - any failure means "not usable"
                return RuntimeDetection(
                    self.runtime_type.value,
                    False,
                    details={"mode": "api", "reason": str(exc)[:300]},
                )
            return RuntimeDetection(
                self.runtime_type.value,
                True,
                version=info.get("git_version"),
                details={"mode": "api", "platform": info.get("platform")},
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

    # --- observation --------------------------------------------------------------------
    def _read_deployment(
        self, ctx: RuntimeContext, desired: DesiredApplicationState | None = None
    ) -> dict[str, Any] | None:
        namespace = self._namespace(ctx, desired)
        name = self._deployment_name(ctx, desired)
        if self._api_mode(ctx):
            return self._api(ctx).read("Deployment", name, namespace)
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

    def _pods(self, ctx: RuntimeContext) -> list[dict[str, Any]]:
        if not self._api_mode(ctx):
            return []
        try:
            return self._api(ctx).list_pods(self._namespace(ctx), self._selector(ctx))
        except RuntimeOperationError:
            return []

    def _events(
        self, ctx: RuntimeContext, desired: DesiredApplicationState | None = None
    ) -> list[dict[str, Any]]:
        """Recent cluster events for the workload: they explain most failed rollouts."""
        namespace = self._namespace(ctx, desired)
        name = self._deployment_name(ctx, desired)
        if self._api_mode(ctx):
            try:
                return self._api(ctx).events(namespace, selector=name, limit=15)
            except RuntimeOperationError:
                return []
        result = ctx.run(
            self._kubectl(
                ctx,
                "get",
                "events",
                "-n",
                namespace,
                "--sort-by=.lastTimestamp",
                "-o",
                "json",
                command_type="events",
                description="Read namespace events",
                allow_failure=True,
                timeout=60,
            ),
            label="Read events",
        )
        if not result.ok or not result.stdout.strip():
            return []
        try:
            items = (json.loads(result.stdout) or {}).get("items") or []
        except json.JSONDecodeError:
            return []
        events = []
        for item in items[-15:]:
            involved = item.get("involvedObject") or {}
            if name not in (involved.get("name") or ""):
                continue
            events.append(
                {
                    "type": item.get("type"),
                    "reason": item.get("reason"),
                    "message": (item.get("message") or "")[:400],
                    "object": f"{involved.get('kind')}/{involved.get('name')}",
                    "count": item.get("count"),
                    "last_seen": item.get("lastTimestamp"),
                }
            )
        return events

    def status(self, ctx: RuntimeContext) -> ActualApplicationState:
        actual = ActualApplicationState(
            application_code=ctx.application_code, runtime=self.runtime_type.value
        )
        data = self._read_deployment(ctx)
        if data is None:
            actual.state = ApplicationState.NOT_INSTALLED
            actual.message = "Deployment not found in the namespace."
            actual.details = {
                "namespace": self._namespace(ctx),
                "deployment": self._deployment_name(ctx),
                "mode": "api" if self._api_mode(ctx) else "kubectl",
            }
            return actual
        spec = data.get("spec") or {}
        status = data.get("status") or {}
        metadata = data.get("metadata") or {}
        labels = metadata.get("labels") or {}
        template_labels = ((spec.get("template") or {}).get("metadata") or {}).get("labels") or {}
        desired_replicas = int(spec.get("replicas") or 0)
        ready = int(status.get("readyReplicas") or status.get("ready_replicas") or 0)
        available = int(status.get("availableReplicas") or status.get("available_replicas") or 0)
        conditions = status.get("conditions") or []
        actual.replicas = ready
        actual.version = labels.get(VERSION_LABEL) or template_labels.get(VERSION_LABEL)
        containers = ((spec.get("template") or {}).get("spec") or {}).get("containers") or []
        if containers:
            actual.image = containers[0].get("image")
        if desired_replicas == 0:
            actual.state = ApplicationState.STOPPED
        elif ready >= desired_replicas > 0:
            actual.state = ApplicationState.RUNNING
            actual.health = HealthStatus.HEALTHY
        elif ready == 0 and any(
            (c.get("type") == "Progressing" and str(c.get("status")) == "False") for c in conditions
        ):
            actual.state = ApplicationState.FAILED
            actual.health = HealthStatus.UNHEALTHY
        else:
            actual.state = ApplicationState.STARTING
        actual.details = {
            "mode": "api" if self._api_mode(ctx) else "kubectl",
            "namespace": self._namespace(ctx),
            "deployment": self._deployment_name(ctx),
            "desired_replicas": desired_replicas,
            "ready_replicas": ready,
            "available_replicas": available,
            "updated_replicas": status.get("updatedReplicas") or status.get("updated_replicas"),
            "generation": metadata.get("generation"),
            "observed_generation": status.get("observedGeneration")
            or status.get("observed_generation"),
            "conditions": [
                {"type": c.get("type"), "status": str(c.get("status")), "reason": c.get("reason")}
                for c in conditions
            ],
        }
        pods = self._pods(ctx)
        if pods:
            actual.details["pods"] = pods
        if actual.state in {ApplicationState.FAILED, ApplicationState.STARTING}:
            events = self._events(ctx)
            if events:
                actual.details["events"] = events
        return actual

    def version(self, ctx: RuntimeContext) -> str | None:
        return self.status(ctx).version

    def inspect(self, ctx: RuntimeContext) -> dict[str, Any]:
        data = self._read_deployment(ctx) or {}
        spec = data.get("spec") or {}
        template = (spec.get("template") or {}).get("spec") or {}
        containers = [
            {
                "name": c.get("name"),
                "image": c.get("image"),
                "ports": c.get("ports"),
                "resources": c.get("resources"),
                "env_from": [
                    (e.get("secretRef") or e.get("configMapRef") or {}).get("name")
                    for e in c.get("envFrom") or []
                ],
            }
            for c in template.get("containers") or []
        ]
        return {
            "metadata": {
                key: (data.get("metadata") or {}).get(key)
                for key in ("name", "namespace", "labels", "generation", "creationTimestamp")
            },
            "replicas": spec.get("replicas"),
            "strategy": spec.get("strategy"),
            "containers": containers,
            "status": data.get("status"),
            "pods": self._pods(ctx),
            "events": self._events(ctx),
        }

    def logs(self, ctx: RuntimeContext, lines: int = 200, since: str | None = None) -> LogChunk:
        lines = validate_int_range(lines, field="lines", minimum=1, maximum=5000)
        namespace = self._namespace(ctx)
        name = self._deployment_name(ctx)
        since_seconds = None
        if since:
            match = SINCE_PATTERN.fullmatch(since)
            if not match:
                raise ValidationError(
                    "Invalid 'since' value.", errors={"since": ["Use a form like 10m or 2h."]}
                )
            since_seconds = int(match.group(1)) * SINCE_SECONDS[match.group(2)]

        if self._api_mode(ctx):
            api = self._api(ctx)
            pods = api.list_pods(namespace, self._selector(ctx))
            if not pods:
                return LogChunk(lines=[], source=f"kubernetes ns={namespace}", truncated=False)
            out: list[str] = []
            for pod in pods[:5]:
                text = api.pod_logs(
                    namespace, pod["name"], lines=lines, since_seconds=since_seconds
                )
                out.extend(f"[{pod['name']}] {line}" for line in text.splitlines())
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
            lines=out[-lines:],
            source=f"kubectl logs deployment/{name}",
            truncated=len(out) > lines,
        )

    def health(
        self, ctx: RuntimeContext, spec: HealthSpec, desired: DesiredApplicationState | None = None
    ) -> HealthResult:
        started = time.monotonic()
        actual = self.status(ctx)
        elapsed = round(time.monotonic() - started, 3)
        if actual.state == ApplicationState.RUNNING:
            return HealthResult(
                HealthStatus.HEALTHY,
                f"{actual.replicas} ready replica(s)",
                details=actual.details,
                duration_seconds=elapsed,
            )
        message = f"Deployment state is {actual.state.value}"
        events = actual.details.get("events") or []
        if events:
            message = f"{message}: {events[0].get('reason')} {events[0].get('message', '')[:120]}"
        return HealthResult(
            HealthStatus.UNHEALTHY, message, details=actual.details, duration_seconds=elapsed
        )

    # --- configuration -------------------------------------------------------------------
    def configure(
        self, ctx: RuntimeContext, desired: DesiredApplicationState, env: dict[str, str]
    ) -> dict[str, Any]:
        """Publish the rendered configuration as a Secret the workload reads with envFrom.

        There is no file to write on a host: in Kubernetes the configuration belongs to the
        cluster. Values never appear in a log line, only the key names do.
        """
        namespace = self._namespace(ctx, desired)
        name = self.secret_name(ctx)
        if self._api_mode(ctx):
            api = self._api(ctx)
            api.ensure_namespace(namespace)
            api.apply(
                {
                    "apiVersion": "v1",
                    "kind": "Secret",
                    "type": "Opaque",
                    "metadata": {
                        "name": name,
                        "namespace": namespace,
                        "labels": {APP_LABEL: ctx.application_code, MANAGED_BY: "scarlet"},
                    },
                    "stringData": {str(k): str(v) for k, v in env.items()},
                },
                namespace,
            )
        else:
            env_file = ctx.layout.env_file
            ctx.run(
                self._kubectl(
                    ctx,
                    "delete",
                    "secret",
                    name,
                    "-n",
                    namespace,
                    "--ignore-not-found=true",
                    command_type="delete_secret",
                    description="Drop the previous configuration secret",
                    allow_failure=True,
                    timeout=60,
                ),
                label="Delete previous secret",
            )
            ctx.run(
                self._kubectl(
                    ctx,
                    "create",
                    "secret",
                    "generic",
                    name,
                    "-n",
                    namespace,
                    f"--from-env-file={env_file}",
                    command_type="create_secret",
                    description="Create the configuration secret",
                    timeout=120,
                ),
                label="Create configuration secret",
            )
            ctx.run(
                self._kubectl(
                    ctx,
                    "label",
                    "secret",
                    name,
                    "-n",
                    namespace,
                    f"{APP_LABEL}={ctx.application_code}",
                    f"{MANAGED_BY}=scarlet",
                    "--overwrite",
                    command_type="label",
                    description="Label the configuration secret",
                    allow_failure=True,
                    timeout=60,
                ),
                label="Label secret",
            )
        ctx.log(
            "INFO",
            f"{len(env)} configuration key(s) published as Secret {name} "
            f"in namespace {namespace} (values not logged)",
        )
        return {"secret": name, "namespace": namespace, "keys": sorted(env.keys())}

    # --- mutation -------------------------------------------------------------------------
    def install(
        self, ctx: RuntimeContext, desired: DesiredApplicationState, release_dir: str
    ) -> dict[str, Any]:
        namespace = self._namespace(ctx, desired)
        if self._api_mode(ctx):
            api = self._api(ctx)
            docs = self._local_manifest_docs(ctx, desired)
            created_ns = False
            if not any(doc.get("kind") == "Namespace" for doc in docs):
                created_ns = api.ensure_namespace(namespace)
            applied: list[str] = []
            for doc in docs:
                if doc.get("kind") not in CLUSTER_KINDS:
                    doc.setdefault("metadata", {})["namespace"] = namespace
                self._decorate(ctx, doc, desired)
                applied.append(api.apply(doc, namespace))
                ctx.log("INFO", f"Applied {applied[-1]} in namespace {namespace}")
            return {
                "mode": "api",
                "namespace": namespace,
                "namespace_created": created_ns,
                "applied": applied,
                "image": desired.image,
            }

        manifests_dir = self._k8s_manifest(desired).get("manifests")
        if not manifests_dir:
            raise RuntimeOperationError(
                "kubectl mode requires kubernetes.manifests in the release manifest."
            )
        remote_dir = validate_remote_path(f"{release_dir}/{manifests_dir}", ctx.layout.base_path)
        ctx.run(
            self._kubectl(
                ctx,
                "create",
                "namespace",
                namespace,
                command_type="create_namespace",
                description="Ensure the namespace exists",
                allow_failure=True,
                timeout=60,
            ),
            label="Ensure namespace",
        )
        ctx.run(
            self._kubectl(
                ctx,
                "apply",
                "-n",
                namespace,
                "-f",
                remote_dir,
                command_type="apply",
                description="Apply the release objects",
                timeout=300,
            ),
            label="Apply objects",
        )
        name = self._deployment_name(ctx, desired)
        container = self._container_name(ctx, desired)
        patch = {
            "spec": {
                "template": {
                    "metadata": {
                        "labels": {
                            APP_LABEL: ctx.application_code,
                            VERSION_LABEL: desired.version,
                        }
                    },
                    "spec": {
                        "containers": [
                            {
                                "name": container,
                                "envFrom": [
                                    {"secretRef": {"name": self.secret_name(ctx), "optional": True}}
                                ],
                                **({"image": desired.image} if desired.image else {}),
                            }
                        ]
                    },
                }
            }
        }
        ctx.run(
            self._kubectl(
                ctx,
                "patch",
                "deployment",
                name,
                "-n",
                namespace,
                "--type=strategic",
                "-p",
                json.dumps(patch, separators=(",", ":")),
                command_type="patch",
                description="Wire image and configuration into the workload",
                timeout=60,
            ),
            label="Patch deployment",
        )
        ctx.run(
            self._kubectl(
                ctx,
                "label",
                "deployment",
                name,
                "-n",
                namespace,
                f"{VERSION_LABEL}={desired.version}",
                f"{APP_LABEL}={ctx.application_code}",
                f"{MANAGED_BY}=scarlet",
                "--overwrite",
                command_type="label",
                description="Label the workload",
                allow_failure=True,
                timeout=60,
            ),
            label="Label deployment",
        )
        return {
            "mode": "kubectl",
            "namespace": namespace,
            "manifests": remote_dir,
            "image": desired.image,
        }

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

    def _rollout_failure(
        self, ctx: RuntimeContext, desired: DesiredApplicationState | None, message: str
    ) -> RuntimeOperationError:
        events = self._events(ctx, desired)
        pods = self._pods(ctx)
        for event in events[:3]:
            ctx.log("ERROR", f"{event.get('object')}: {event.get('reason')} {event.get('message')}")
        return RuntimeOperationError(message, details={"events": events, "pods": pods})

    def _wait_rollout(self, ctx: RuntimeContext, desired: DesiredApplicationState | None) -> None:
        namespace = self._namespace(ctx, desired)
        name = self._deployment_name(ctx, desired)
        timeout = int(
            ((desired.manifest.get("deployment") or {}).get("start_timeout") if desired else None)
            or 120
        )
        if self._api_mode(ctx):
            deadline = time.monotonic() + timeout
            while True:
                actual = self.status(ctx)
                if actual.state in {ApplicationState.RUNNING, ApplicationState.STOPPED}:
                    return
                if actual.state == ApplicationState.FAILED:
                    raise self._rollout_failure(ctx, desired, "The rollout failed.")
                if time.monotonic() >= deadline:
                    raise self._rollout_failure(
                        ctx, desired, f"The rollout did not complete within {timeout}s."
                    )
                time.sleep(2)
        result = ctx.run(
            self._kubectl(
                ctx,
                "rollout",
                "status",
                f"deployment/{name}",
                "-n",
                namespace,
                f"--timeout={timeout}s",
                command_type="rollout_status",
                description="Wait for the rollout",
                allow_failure=True,
                timeout=timeout + 30,
            ),
            label="Wait for rollout",
        )
        if not result.ok:
            raise self._rollout_failure(
                ctx, desired, f"The rollout failed: {result.stderr.strip()[:200]}"
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
            self._api(ctx).restart(name, namespace)
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
            self._api(ctx).scale(name, namespace, replicas)
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
                    description="Scale the deployment",
                    timeout=60,
                ),
                label="Scale deployment",
            )
        return self.status(ctx)

    def remove(self, ctx: RuntimeContext) -> None:
        namespace = self._namespace(ctx)
        selector = self._selector(ctx)
        if self._api_mode(ctx):
            removed = self._api(ctx).delete_by_label(CLEANUP_KINDS, namespace, selector)
            ctx.log("INFO", f"Removed {len(removed)} object(s) from namespace {namespace}")
            return
        ctx.run(
            self._kubectl(
                ctx,
                "delete",
                ",".join(kind.lower() for kind in CLEANUP_KINDS),
                "-n",
                namespace,
                "-l",
                selector,
                "--ignore-not-found=true",
                command_type="delete",
                description="Delete the application objects",
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
