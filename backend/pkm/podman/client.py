"""Podman integration layer.

Talks to the Podman REST API (libpod endpoints, compatible with Podman 4.x and 5.x)
over the unix socket exposed by `podman.socket` (or an http URL on a trusted network).
Podman is a separate runtime from Kubernetes: nothing here touches the cluster.
"""

from __future__ import annotations

import json
import logging
import struct
from abc import ABC, abstractmethod
from typing import Any
from urllib.parse import quote, urlparse

import httpx

from ..config import PodmanConfig
from ..errors import (
    AppError,
    PodmanError,
    PodmanNotConfigured,
    PodmanNotFound,
    PodmanTimeout,
    PodmanUnavailable,
)

log = logging.getLogger("pkm.podman")

API_PREFIX = "/v4.0.0/libpod"


def container_summary(c: dict[str, Any]) -> dict[str, Any]:
    names = c.get("Names") or []
    ports = []
    for p in c.get("Ports") or []:
        host = p.get("host_port") or p.get("hostPort")
        cport = p.get("container_port") or p.get("containerPort")
        if cport:
            ports.append(f"{p.get('host_ip') or '0.0.0.0'}:{host}->{cport}/{p.get('protocol', 'tcp')}"  # noqa: S104
                         if host else f"{cport}/{p.get('protocol', 'tcp')}")  # fmt: skip
    return {
        "id": (c.get("Id") or "")[:12],
        "fullId": c.get("Id"),
        "name": names[0] if names else (c.get("Id") or "")[:12],
        "image": c.get("Image"),
        "imageId": (c.get("ImageID") or "")[:12],
        "state": c.get("State"),
        "status": c.get("Status"),
        "exitCode": c.get("ExitCode"),
        "created": c.get("Created") if isinstance(c.get("Created"), str) else c.get("CreatedAt"),
        "startedAt": c.get("StartedAt"),
        "ports": ports,
        "pod": c.get("PodName") or None,
        "labels": c.get("Labels") or {},
        "command": " ".join(c.get("Command") or []),
        "isInfra": bool(c.get("IsInfra")),
    }


def image_summary(i: dict[str, Any]) -> dict[str, Any]:
    tags = i.get("RepoTags") or i.get("Names") or []
    return {
        "id": (i.get("Id") or "").replace("sha256:", "")[:12],
        "fullId": i.get("Id"),
        "tags": tags,
        "size": i.get("Size"),
        "created": i.get("Created"),
        "containers": i.get("Containers", 0),
        "dangling": not tags or tags == ["<none>:<none>"],
        "digest": i.get("Digest"),
    }


class PodmanProvider(ABC):
    demo = False

    @abstractmethod
    def info(self) -> dict[str, Any]: ...

    @abstractmethod
    def list_containers(self, all_: bool = True) -> list[dict[str, Any]]: ...

    @abstractmethod
    def inspect_container(self, cid: str) -> dict[str, Any]: ...

    @abstractmethod
    def container_logs(self, cid: str, *, tail: int, timestamps: bool, since: int | None = None) -> list[str]: ...

    @abstractmethod
    def container_action(self, cid: str, action: str) -> None:
        """action: start | stop | restart"""

    @abstractmethod
    def remove_container(self, cid: str, force: bool = False) -> None: ...

    @abstractmethod
    def list_images(self) -> list[dict[str, Any]]: ...

    @abstractmethod
    def inspect_image(self, iid: str) -> dict[str, Any]: ...

    @abstractmethod
    def remove_image(self, iid: str, force: bool = False) -> None: ...

    @abstractmethod
    def pull_image(self, reference: str) -> dict[str, Any]: ...

    @abstractmethod
    def stats(self) -> list[dict[str, Any]]: ...

    def close(self) -> None:  # noqa: B027
        pass


def _client_for(cfg: PodmanConfig, timeout: float) -> tuple[httpx.Client, str]:
    u = urlparse(cfg.url)
    if u.scheme == "unix":
        transport = httpx.HTTPTransport(uds=u.path, retries=1)
        return httpx.Client(transport=transport, base_url="http://podman", timeout=timeout), u.path
    if u.scheme in ("http", "https"):
        transport = httpx.HTTPTransport(retries=1)
        return httpx.Client(transport=transport, base_url=cfg.url.rstrip("/"), timeout=timeout), cfg.url
    raise PodmanNotConfigured(f"unsupported Podman URL scheme '{u.scheme}'", params={"url": cfg.url})


class LivePodman(PodmanProvider):
    def __init__(self, cfg: PodmanConfig) -> None:
        self.cfg = cfg
        self._client: httpx.Client | None = None
        self._init_error: AppError | None = None
        self.endpoint: str | None = None
        if not cfg.enabled:
            self._init_error = PodmanNotConfigured("Podman integration is disabled in the configuration")
            return
        try:
            self._client, self.endpoint = _client_for(cfg, cfg.timeout)
        except AppError as exc:
            self._init_error = exc

    def _req(self, method: str, path: str, *, params: dict[str, Any] | None = None,
             timeout: float | None = None, expect_json: bool = True) -> Any:  # fmt: skip
        if self._client is None:
            raise self._init_error or PodmanNotConfigured("Podman is not configured")
        try:
            resp = self._client.request(method, API_PREFIX + path, params=params,
                                        timeout=timeout or self.cfg.timeout)  # fmt: skip
        except httpx.ConnectTimeout as exc:
            raise PodmanUnavailable("cannot connect to the Podman API", details=f"ConnectTimeout: {exc}",
                                    params={"endpoint": self.endpoint}) from exc  # fmt: skip
        except httpx.TimeoutException as exc:
            raise PodmanTimeout("Podman did not answer in time", details=str(exc)) from exc
        except (httpx.TransportError, OSError) as exc:
            raise PodmanUnavailable("cannot connect to the Podman API", details=f"{type(exc).__name__}: {exc}",
                                    params={"endpoint": self.endpoint}) from exc  # fmt: skip
        if resp.status_code >= 400:
            try:
                body = resp.json()
                msg = body.get("message") or body.get("cause") or resp.text
            except ValueError:
                msg = resp.text[:500]
            if resp.status_code == 404:
                raise PodmanNotFound(msg, details=msg)
            raise PodmanError(msg, details=msg, params={"status": resp.status_code})
        if not expect_json:
            return resp
        if not resp.content:
            return None
        try:
            return resp.json()
        except ValueError as exc:
            raise PodmanError("unexpected response from Podman", details=resp.text[:500]) from exc

    def info(self) -> dict[str, Any]:
        base = {"connected": False, "configured": self._client is not None, "endpoint": self.endpoint}
        try:
            info = self._req("GET", "/info")
            ver = self._req("GET", "/version")
        except AppError as exc:
            return {**base, "error": {"code": exc.code, "message": exc.message, "details": exc.details,
                                      "params": exc.params}}  # fmt: skip
        host = info.get("host") or {}
        store = info.get("store") or {}
        sec = host.get("security") or {}
        registries = info.get("registries") or {}
        return {
            **base,
            "connected": True,
            "version": ver.get("Version") or (info.get("version") or {}).get("Version"),
            "apiVersion": ver.get("ApiVersion") or (info.get("version") or {}).get("APIVersion"),
            "os": host.get("os"), "arch": host.get("arch"), "hostname": host.get("hostname"),
            "kernel": host.get("kernel"), "distribution": host.get("distribution"),
            "rootless": sec.get("rootless"), "selinux": sec.get("selinuxEnabled"),
            "cgroupVersion": host.get("cgroupVersion"), "ociRuntime": (host.get("ociRuntime") or {}).get("name"),
            "storageDriver": store.get("graphDriverName"), "graphRoot": store.get("graphRoot"),
            "containers": (store.get("containerStore") or {}), "images": (store.get("imageStore") or {}).get("number"),
            "registries": {"search": registries.get("search") or [],
                           "configured": {k: v for k, v in registries.items() if k != "search"}},
            "cpus": host.get("cpus"), "memTotal": host.get("memTotal"), "memFree": host.get("memFree"),
            "uptime": host.get("uptime"),
        }  # fmt: skip

    def list_containers(self, all_=True):
        return [container_summary(c) for c in self._req("GET", "/containers/json", params={"all": str(all_).lower()}) or []]

    def inspect_container(self, cid):
        return self._req("GET", f"/containers/{quote(cid, safe='')}/json")

    def container_logs(self, cid, *, tail, timestamps, since=None):
        data = self.inspect_container(cid)
        tty = bool((data.get("Config") or {}).get("Tty"))
        params: dict[str, Any] = {"stdout": "true", "stderr": "true", "tail": str(tail),
                                  "timestamps": str(timestamps).lower()}  # fmt: skip
        if since:
            params["since"] = str(since)
        resp = self._req("GET", f"/containers/{quote(cid, safe='')}/logs", params=params, expect_json=False,
                         timeout=max(self.cfg.timeout, 30))  # fmt: skip
        raw = resp.content
        text = raw.decode("utf-8", errors="replace") if tty else _demux(raw)
        lines = text.splitlines()
        return lines[-tail:] if tail else lines

    def container_action(self, cid, action):
        if action not in ("start", "stop", "restart"):
            raise PodmanError(f"unsupported action {action}")
        params = {"timeout": "10"} if action == "stop" else ({"t": "10"} if action == "restart" else None)
        self._req("POST", f"/containers/{quote(cid, safe='')}/{action}", params=params, timeout=60, expect_json=False)

    def remove_container(self, cid, force=False):
        self._req("DELETE", f"/containers/{quote(cid, safe='')}", params={"force": str(force).lower()}, timeout=60,
                  expect_json=False)  # fmt: skip

    def list_images(self):
        return [image_summary(i) for i in self._req("GET", "/images/json") or []]

    def inspect_image(self, iid):
        return self._req("GET", f"/images/{quote(iid, safe='')}/json")

    def remove_image(self, iid, force=False):
        self._req("DELETE", f"/images/{quote(iid, safe='')}", params={"force": str(force).lower()}, timeout=60)

    def pull_image(self, reference):
        resp = self._req("POST", "/images/pull", params={"reference": reference, "quiet": "true"}, timeout=600,
                         expect_json=False)  # fmt: skip
        result: dict[str, Any] = {"reference": reference}
        for line in resp.text.splitlines():
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if msg.get("error"):
                raise PodmanError(msg["error"], details=msg["error"], params={"reference": reference})
            if msg.get("id"):
                result["id"] = msg["id"]
            if msg.get("images"):
                result["images"] = msg["images"]
        return result

    def stats(self):
        data = self._req("GET", "/containers/stats", params={"stream": "false"}, timeout=max(self.cfg.timeout, 20))
        out = []
        for s in (data or {}).get("Stats") or []:
            out.append({"id": (s.get("ContainerID") or "")[:12], "name": s.get("Name"),
                        "cpuPercent": s.get("CPU"), "memUsage": s.get("MemUsage"), "memLimit": s.get("MemLimit"),
                        "memPercent": s.get("MemPerc"), "netInput": s.get("NetInput"), "netOutput": s.get("NetOutput"),
                        "blockInput": s.get("BlockInput"), "blockOutput": s.get("BlockOutput"), "pids": s.get("PIDs")})  # fmt: skip
        return out

    def close(self) -> None:
        if self._client is not None:
            self._client.close()


def _demux(raw: bytes) -> str:
    """Decode the Docker/Podman multiplexed log stream (8-byte frame headers)."""
    out = []
    i = 0
    n = len(raw)
    while i + 8 <= n:
        stream_type = raw[i]
        if stream_type not in (0, 1, 2, 3) or raw[i + 1:i + 4] != b"\x00\x00\x00":
            # Not multiplexed after all: return the raw text.
            return raw.decode("utf-8", errors="replace")
        (size,) = struct.unpack(">I", raw[i + 4:i + 8])
        out.append(raw[i + 8:i + 8 + size])
        i += 8 + size
    return b"".join(out).decode("utf-8", errors="replace")


def build_podman(settings: Any) -> PodmanProvider:
    if settings.is_demo:
        from .demo import DemoPodman

        return DemoPodman()
    return LivePodman(settings.podman)
