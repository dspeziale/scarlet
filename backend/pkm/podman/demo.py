"""DEMO Podman runtime (in memory). Only used with `mode: demo`."""

from __future__ import annotations

import copy
import threading
from datetime import UTC, datetime, timedelta
from typing import Any

from ..errors import PodmanError, PodmanNotFound
from .client import PodmanProvider, container_summary, image_summary


def _ts(delta: timedelta) -> str:
    return (datetime.now(UTC) - delta).isoformat()


class DemoPodman(PodmanProvider):
    demo = True

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._images: dict[str, dict[str, Any]] = {}
        for i, (tag, size) in enumerate([("docker.io/library/postgres:16.4", 438_000_000),
                                         ("docker.io/library/nginx:1.27.2", 192_000_000),
                                         ("quay.io/prometheus/node-exporter:v1.8.2", 23_000_000),
                                         ("registry.example.com/tools/report-builder:3.1", 512_000_000),
                                         ("<none>:<none>", 87_000_000)]):  # fmt: skip
            iid = f"{i + 1:02d}" + "ab34cd56ef7890" * 4
            self._images[iid] = {"Id": iid, "RepoTags": [] if tag.startswith("<none>") else [tag], "Size": size,
                                 "Created": int((datetime.now(UTC) - timedelta(days=10 * (i + 1))).timestamp()),
                                 "Containers": 0}  # fmt: skip
        self._containers: dict[str, dict[str, Any]] = {}
        for i, (name, image, state, code, ports) in enumerate([
            ("pg-reporting", "docker.io/library/postgres:16.4", "running", 0, [(5432, 5432)]),
            ("edge-proxy", "docker.io/library/nginx:1.27.2", "running", 0, [(8081, 80)]),
            ("node-exporter", "quay.io/prometheus/node-exporter:v1.8.2", "running", 0, [(9100, 9100)]),
            ("report-builder", "registry.example.com/tools/report-builder:3.1", "exited", 1, []),
            ("migration-tool", "registry.example.com/tools/report-builder:3.1", "created", 0, []),
        ]):  # fmt: skip
            cid = f"c{i + 1}" + "0f1e2d3c4b5a69" * 4
            self._containers[cid] = {
                "Id": cid, "Names": [name], "Image": image, "ImageID": next(
                    (k for k, v in self._images.items() if image in v["RepoTags"]), ""),
                "State": state, "ExitCode": code, "Created": _ts(timedelta(days=3 + i)),
                "StartedAt": _ts(timedelta(hours=5 + i)) if state != "created" else None,
                "Status": {"running": f"Up {5 + i} hours", "exited": f"Exited ({code}) 2 hours ago",
                           "created": "Created"}[state],
                "Ports": [{"host_ip": "", "host_port": h, "container_port": c, "protocol": "tcp"} for h, c in ports],
                "Labels": {"io.podman.demo": "true"}, "Command": ["/entrypoint.sh"], "PodName": "",
            }  # fmt: skip

    def info(self) -> dict[str, Any]:
        running = sum(1 for c in self._containers.values() if c["State"] == "running")
        return {"connected": True, "configured": True, "endpoint": "unix:///run/podman/podman.sock (demo)",
                "version": "5.4.0-demo", "apiVersion": "5.4.0", "os": "linux", "arch": "amd64",
                "hostname": "ol9-demo", "kernel": "5.15.0-310.184.5.2.el9uek.x86_64",
                "distribution": {"distribution": "ol", "version": "9.7"}, "rootless": False, "selinux": True,
                "cgroupVersion": "v2", "ociRuntime": "crun", "storageDriver": "overlay",
                "graphRoot": "/var/lib/containers/storage",
                "containers": {"number": len(self._containers), "running": running,
                               "stopped": len(self._containers) - running, "paused": 0},
                "images": len(self._images),
                "registries": {"search": ["container-registry.oracle.com", "docker.io", "quay.io"], "configured": {}},
                "cpus": 8, "memTotal": 33_554_432_000, "memFree": 12_884_901_888, "uptime": "312h 4m", "demo": True}  # fmt: skip

    def _find(self, cid: str) -> dict[str, Any]:
        for k, c in self._containers.items():
            if k.startswith(cid) or cid in c["Names"]:
                return c
        raise PodmanNotFound(f"no container with name or ID {cid} found")

    def list_containers(self, all_=True):
        return [container_summary(c) for c in self._containers.values() if all_ or c["State"] == "running"]

    def inspect_container(self, cid):
        c = copy.deepcopy(self._find(cid))
        return {"Id": c["Id"], "Name": c["Names"][0], "ImageName": c["Image"], "Image": c["ImageID"],
                "Created": c["Created"], "State": {"Status": c["State"], "Running": c["State"] == "running",
                                                   "ExitCode": c["ExitCode"], "StartedAt": c["StartedAt"]},
                "Config": {"Tty": False, "Env": ["PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin"],
                           "Cmd": c["Command"], "Labels": c["Labels"]},
                "HostConfig": {"RestartPolicy": {"Name": "always" if c["State"] == "running" else "no"}},
                "NetworkSettings": {"Ports": {f"{p['container_port']}/tcp": [{"HostPort": str(p["host_port"])}]
                                              for p in c["Ports"]}},
                "Mounts": []}  # fmt: skip

    def container_logs(self, cid, *, tail, timestamps, since=None):
        c = self._find(cid)
        name = c["Names"][0]
        if c["State"] == "exited":
            base = ["[DEMO] starting report-builder 3.1", "[DEMO] reading /config/report.yaml",
                    "[DEMO] ERROR: config file /config/report.yaml not found", "[DEMO] exiting with status 1"]  # fmt: skip
        elif c["State"] == "created":
            base = []
        else:
            base = [f"[DEMO] {name}: request handled in {12 + i % 40}ms" for i in range(200)]
        now = datetime.now(UTC)
        lines = [f"{(now - timedelta(seconds=(len(base) - i) * 5)).isoformat()} {ln}" if timestamps else ln
                 for i, ln in enumerate(base)]  # fmt: skip
        return lines[-tail:] if tail else lines

    def container_action(self, cid, action):
        with self._lock:
            c = self._find(cid)
            if action in ("start", "restart"):
                c.update(State="running", Status="Up 1 second", StartedAt=_ts(timedelta(0)), ExitCode=0)
            elif action == "stop":
                c.update(State="exited", Status="Exited (0) 1 second ago", ExitCode=0)
            else:
                raise PodmanError(f"unsupported action {action}")

    def remove_container(self, cid, force=False):
        with self._lock:
            c = self._find(cid)
            if c["State"] == "running" and not force:
                raise PodmanError("cannot remove container: container is running (use force)", params={"status": 409})
            self._containers.pop(c["Id"])

    def list_images(self):
        return [image_summary({**i, "Containers": sum(1 for c in self._containers.values() if c["ImageID"] == k)})
                for k, i in self._images.items()]  # fmt: skip

    def inspect_image(self, iid):
        for k, i in self._images.items():
            if k.startswith(iid) or iid in i["RepoTags"]:
                return {**copy.deepcopy(i), "Architecture": "amd64", "Os": "linux",
                        "Config": {"Labels": {"io.podman.demo": "true"}}}  # fmt: skip
        raise PodmanNotFound(f"{iid}: image not known")

    def remove_image(self, iid, force=False):
        with self._lock:
            img = self.inspect_image(iid)
            if any(c["ImageID"] == img["Id"] for c in self._containers.values()) and not force:
                raise PodmanError("image is in use by a container", params={"status": 409})
            self._images.pop(img["Id"])

    def pull_image(self, reference):
        if "notfound" in reference:
            raise PodmanError(f"{reference}: manifest unknown", params={"reference": reference})
        with self._lock:
            iid = "ff" + str(abs(hash(reference)))[:10].ljust(62, "0")
            self._images[iid] = {"Id": iid, "RepoTags": [reference], "Size": 50_000_000,
                                 "Created": int(datetime.now(UTC).timestamp()), "Containers": 0}  # fmt: skip
        return {"reference": reference, "id": iid, "demo": True}

    def stats(self):
        out = []
        for i, c in enumerate(self._containers.values()):
            if c["State"] != "running":
                continue
            out.append({"id": c["Id"][:12], "name": c["Names"][0], "cpuPercent": 1.5 + i * 3.2,
                        "memUsage": (120 + i * 60) * 2**20, "memLimit": 33_554_432_000,
                        "memPercent": round((120 + i * 60) * 2**20 / 33_554_432_000 * 100, 2),
                        "netInput": 10_000_000 * (i + 1), "netOutput": 4_000_000 * (i + 1),
                        "blockInput": 0, "blockOutput": 0, "pids": 4 + i})  # fmt: skip
        return out
