"""Guided deployment: turn a simple, validated form into Kubernetes manifests + risk analysis."""

from __future__ import annotations

import re
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

from .naming import LABEL_VALUE, is_label, is_subdomain
from .quantity import bytes_, cpu_cores, is_valid_cpu, is_valid_memory

ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*$")
IMAGE_REPO = re.compile(r"^[a-z0-9]+([._/:-][a-z0-9]+)*$")
TAG = re.compile(r"^[\w][\w.-]{0,127}$")
PATH = re.compile(r"^/[A-Za-z0-9._~!$&'()*+,;=:@%/-]*$")
MANAGED_BY = "pkm"


class Probe(BaseModel):
    type: Literal["none", "http", "tcp"] = "none"
    path: str = "/"
    port: int | None = Field(None, ge=1, le=65535)
    initial_delay: int = Field(5, ge=0, le=600)
    period: int = Field(10, ge=1, le=300)
    failure_threshold: int = Field(3, ge=1, le=30)

    @field_validator("path")
    @classmethod
    def _path(cls, v: str) -> str:
        if not PATH.match(v):
            raise ValueError("path must start with / and contain only URL characters")
        return v


class EnvVar(BaseModel):
    name: str
    value: str = Field("", max_length=4096)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        if not ENV_NAME.match(v) or len(v) > 128:
            raise ValueError("invalid environment variable name")
        return v


class Storage(BaseModel):
    enabled: bool = False
    size: str = "1Gi"
    storage_class: str | None = None
    mount_path: str = "/data"
    access_mode: Literal["ReadWriteOnce", "ReadWriteMany", "ReadOnlyMany", "ReadWriteOncePod"] = "ReadWriteOnce"

    @field_validator("size")
    @classmethod
    def _size(cls, v: str) -> str:
        if not is_valid_memory(v):
            raise ValueError("invalid size, use e.g. 1Gi or 500Mi")
        return v

    @field_validator("mount_path")
    @classmethod
    def _mount(cls, v: str) -> str:
        if not PATH.match(v) or v == "/":
            raise ValueError("mount path must be an absolute path other than /")
        return v

    @field_validator("storage_class")
    @classmethod
    def _sc(cls, v: str | None) -> str | None:
        if v in (None, ""):
            return None
        if not is_subdomain(v):
            raise ValueError("invalid storage class name")
        return v


class Ingress(BaseModel):
    enabled: bool = False
    host: str = ""
    path: str = "/"
    class_name: str | None = None
    tls_secret: str | None = None

    @field_validator("host")
    @classmethod
    def _host(cls, v: str) -> str:
        v = v.strip().lower()
        if v and not is_subdomain(v.replace("*.", "x.", 1)):
            raise ValueError("invalid host name")
        return v

    @field_validator("path")
    @classmethod
    def _path(cls, v: str) -> str:
        if not PATH.match(v):
            raise ValueError("path must start with /")
        return v

    @field_validator("class_name", "tls_secret")
    @classmethod
    def _names(cls, v: str | None) -> str | None:
        if v in (None, ""):
            return None
        if not is_subdomain(v):
            raise ValueError("invalid name")
        return v


class Networking(BaseModel):
    service_type: Literal["none", "ClusterIP", "NodePort", "LoadBalancer"] = "ClusterIP"
    service_port: int | None = Field(None, ge=1, le=65535)
    node_port: int | None = Field(None, ge=30000, le=32767)
    ingress: Ingress = Field(default_factory=Ingress)


class DeploySpec(BaseModel):
    name: str
    namespace: str = "default"
    create_namespace: bool = False
    image: str
    tag: str = "latest"
    image_pull_secret: str | None = None
    replicas: int = Field(1, ge=0, le=50)
    port: int | None = Field(None, ge=1, le=65535)
    protocol: Literal["TCP", "UDP"] = "TCP"
    cpu_request: str | None = "100m"
    cpu_limit: str | None = None
    memory_request: str | None = "128Mi"
    memory_limit: str | None = "256Mi"
    env: list[EnvVar] = Field(default_factory=list, max_length=100)
    storage: Storage = Field(default_factory=Storage)
    networking: Networking = Field(default_factory=Networking)
    readiness: Probe = Field(default_factory=Probe)
    liveness: Probe = Field(default_factory=Probe)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        if not is_label(v) or len(v) > 50:
            raise ValueError("use lowercase letters, digits and '-', max 50 characters, start/end alphanumeric")
        return v

    @field_validator("namespace")
    @classmethod
    def _ns(cls, v: str) -> str:
        if not is_label(v):
            raise ValueError("invalid namespace name")
        return v

    @field_validator("image")
    @classmethod
    def _image(cls, v: str) -> str:
        v = v.strip()
        if ":" in v.rsplit("/", 1)[-1] or "@" in v:
            raise ValueError("put the tag in the Tag field, not in the image name")
        if not IMAGE_REPO.match(v) or len(v) > 255:
            raise ValueError("invalid image name (e.g. nginx or registry.example.com/team/app)")
        return v

    @field_validator("tag")
    @classmethod
    def _tag(cls, v: str) -> str:
        v = v.strip()
        if not TAG.match(v):
            raise ValueError("invalid tag")
        return v

    @field_validator("image_pull_secret")
    @classmethod
    def _secret(cls, v: str | None) -> str | None:
        if v in (None, ""):
            return None
        if not is_subdomain(v):
            raise ValueError("invalid secret name")
        return v

    @field_validator("cpu_request", "cpu_limit")
    @classmethod
    def _cpu(cls, v: str | None) -> str | None:
        if v in (None, ""):
            return None
        if not is_valid_cpu(v):
            raise ValueError("invalid CPU value: use millicores (250m) or cores (0.5, 2)")
        return v

    @field_validator("memory_request", "memory_limit")
    @classmethod
    def _mem(cls, v: str | None) -> str | None:
        if v in (None, ""):
            return None
        if not is_valid_memory(v):
            raise ValueError("invalid memory value: use Mi or Gi (e.g. 256Mi, 1Gi)")
        return v

    @model_validator(mode="after")
    def _cross(self) -> DeploySpec:
        if self.cpu_request and self.cpu_limit and (cpu_cores(self.cpu_request) or 0) > (cpu_cores(self.cpu_limit) or 0):
            raise ValueError("cpu_request cannot be greater than cpu_limit")
        if self.memory_request and self.memory_limit and \
                (bytes_(self.memory_request) or 0) > (bytes_(self.memory_limit) or 0):  # fmt: skip
            raise ValueError("memory_request cannot be greater than memory_limit")
        net = self.networking
        if net.service_type != "none" and not self.port:
            raise ValueError("a container port is required to create a Service")
        if net.ingress.enabled:
            if net.service_type == "none":
                raise ValueError("an Ingress needs a Service: choose a service type")
            if not net.ingress.host:
                raise ValueError("the Ingress needs a host name")
        if net.node_port and net.service_type not in ("NodePort", "LoadBalancer"):
            raise ValueError("node_port is only valid for NodePort or LoadBalancer services")
        for p in (self.readiness, self.liveness):
            if p.type != "none" and not (p.port or self.port):
                raise ValueError("health checks need a port")
        names = [e.name for e in self.env]
        if len(names) != len(set(names)):
            raise ValueError("duplicate environment variable names")
        if not LABEL_VALUE.match(self.tag):
            raise ValueError("invalid tag")
        return self


def _labels(spec: DeploySpec) -> dict[str, str]:
    return {"app.kubernetes.io/name": spec.name, "app.kubernetes.io/instance": spec.name,
            "app.kubernetes.io/managed-by": MANAGED_BY}  # fmt: skip


def _selector(spec: DeploySpec) -> dict[str, str]:
    return {"app.kubernetes.io/name": spec.name, "app.kubernetes.io/instance": spec.name}


def _probe(p: Probe, default_port: int | None) -> dict[str, Any] | None:
    if p.type == "none":
        return None
    port = p.port or default_port
    out: dict[str, Any] = {"initialDelaySeconds": p.initial_delay, "periodSeconds": p.period,
                           "failureThreshold": p.failure_threshold, "timeoutSeconds": 2}  # fmt: skip
    if p.type == "http":
        out["httpGet"] = {"path": p.path, "port": port}
    else:
        out["tcpSocket"] = {"port": port}
    return out


def generate(spec: DeploySpec) -> list[dict[str, Any]]:
    labels = _labels(spec)
    docs: list[dict[str, Any]] = []
    if spec.create_namespace:
        docs.append({"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": spec.namespace,
                     "labels": {"app.kubernetes.io/managed-by": MANAGED_BY}}})  # fmt: skip
    container: dict[str, Any] = {"name": spec.name, "image": f"{spec.image}:{spec.tag}",
                                 "imagePullPolicy": "Always" if spec.tag == "latest" else "IfNotPresent"}  # fmt: skip
    if spec.port:
        container["ports"] = [{"name": "main", "containerPort": spec.port, "protocol": spec.protocol}]
    resources: dict[str, dict[str, str]] = {}
    for section, key, value in (("requests", "cpu", spec.cpu_request), ("requests", "memory", spec.memory_request),
                                ("limits", "cpu", spec.cpu_limit), ("limits", "memory", spec.memory_limit)):  # fmt: skip
        if value:
            resources.setdefault(section, {})[key] = value
    if resources:
        container["resources"] = resources
    if spec.env:
        container["env"] = [{"name": e.name, "value": e.value} for e in spec.env]
    if (rp := _probe(spec.readiness, spec.port)) is not None:
        container["readinessProbe"] = rp
    if (lp := _probe(spec.liveness, spec.port)) is not None:
        container["livenessProbe"] = lp
    container["securityContext"] = {"allowPrivilegeEscalation": False}
    pod_spec: dict[str, Any] = {"containers": [container]}
    if spec.image_pull_secret:
        pod_spec["imagePullSecrets"] = [{"name": spec.image_pull_secret}]
    if spec.storage.enabled:
        pvc_name = f"{spec.name}-data"
        pvc: dict[str, Any] = {"apiVersion": "v1", "kind": "PersistentVolumeClaim",
                               "metadata": {"name": pvc_name, "namespace": spec.namespace, "labels": labels},
                               "spec": {"accessModes": [spec.storage.access_mode],
                                        "resources": {"requests": {"storage": spec.storage.size}}}}  # fmt: skip
        if spec.storage.storage_class:
            pvc["spec"]["storageClassName"] = spec.storage.storage_class
        docs.append(pvc)
        pod_spec["volumes"] = [{"name": "data", "persistentVolumeClaim": {"claimName": pvc_name}}]
        container["volumeMounts"] = [{"name": "data", "mountPath": spec.storage.mount_path}]
    strategy: dict[str, Any] = {"type": "RollingUpdate", "rollingUpdate": {"maxUnavailable": 0, "maxSurge": 1}}
    if spec.storage.enabled and spec.storage.access_mode in ("ReadWriteOnce", "ReadWriteOncePod"):
        strategy = {"type": "Recreate"}  # an RWO volume cannot be mounted by old and new pod at the same time
    docs.append({
        "apiVersion": "apps/v1", "kind": "Deployment",
        "metadata": {"name": spec.name, "namespace": spec.namespace, "labels": labels,
                     "annotations": {"kubernetes.io/change-cause": f"pkm deploy {spec.image}:{spec.tag}"}},
        "spec": {"replicas": spec.replicas, "revisionHistoryLimit": 10, "selector": {"matchLabels": _selector(spec)},
                 "strategy": strategy,
                 "template": {"metadata": {"labels": labels}, "spec": pod_spec}},
    })  # fmt: skip
    net = spec.networking
    if net.service_type != "none" and spec.port:
        port: dict[str, Any] = {"name": "main", "port": net.service_port or spec.port, "targetPort": "main",
                                "protocol": spec.protocol}  # fmt: skip
        if net.node_port:
            port["nodePort"] = net.node_port
        docs.append({"apiVersion": "v1", "kind": "Service",
                     "metadata": {"name": spec.name, "namespace": spec.namespace, "labels": labels},
                     "spec": {"type": net.service_type, "selector": _selector(spec), "ports": [port]}})  # fmt: skip
        if net.ingress.enabled:
            ing: dict[str, Any] = {
                "apiVersion": "networking.k8s.io/v1", "kind": "Ingress",
                "metadata": {"name": spec.name, "namespace": spec.namespace, "labels": labels},
                "spec": {"rules": [{"host": net.ingress.host, "http": {"paths": [{
                    "path": net.ingress.path, "pathType": "Prefix",
                    "backend": {"service": {"name": spec.name, "port": {"number": port["port"]}}}}]}}]},
            }  # fmt: skip
            if net.ingress.class_name:
                ing["spec"]["ingressClassName"] = net.ingress.class_name
            if net.ingress.tls_secret:
                ing["spec"]["tls"] = [{"hosts": [net.ingress.host], "secretName": net.ingress.tls_secret}]
            docs.append(ing)
    return docs


def risks(spec: DeploySpec) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    def add(level: str, code: str, **params: Any) -> None:
        out.append({"level": level, "code": code, "params": params})

    if spec.replicas == 0:
        add("high", "zero_replicas")
    elif spec.replicas == 1:
        add("medium", "single_replica")
    if spec.tag == "latest":
        add("medium", "latest_tag")
    if not spec.memory_limit:
        add("medium", "no_memory_limit")
    if not spec.cpu_request or not spec.memory_request:
        add("medium", "no_requests")
    if spec.port and spec.readiness.type == "none":
        add("medium", "no_readiness")
    if spec.port and spec.liveness.type == "none":
        add("low", "no_liveness")
    if spec.storage.enabled and spec.storage.access_mode in ("ReadWriteOnce", "ReadWriteOncePod") and spec.replicas > 1:
        add("high", "rwo_multi_replica", replicas=spec.replicas)
    if spec.storage.enabled and spec.storage.access_mode == "ReadWriteOnce":
        add("low", "recreate_strategy")
    if spec.networking.service_type == "NodePort":
        add("medium", "nodeport_exposed")
    if spec.networking.service_type == "LoadBalancer":
        add("medium", "loadbalancer_exposed")
    if spec.networking.ingress.enabled and not spec.networking.ingress.tls_secret:
        add("medium", "ingress_no_tls")
    if any(re.search(r"(PASSWORD|SECRET|TOKEN|KEY)", e.name, re.I) and e.value for e in spec.env):
        add("high", "secret_in_env")
    return out


def to_yaml(docs: list[dict[str, Any]]) -> str:
    return "---\n".join(yaml.safe_dump(d, sort_keys=False, default_flow_style=False) for d in docs)
