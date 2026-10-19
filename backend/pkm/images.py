"""Image onboarding: inspect a container image directly on its registry (OCI Distribution / Registry v2 API).

Used by the "Onboarding immagine" wizard before deploying: verifies that the
reference exists, that the registry is reachable from the PKM host and whether
credentials are required, then reads the image configuration (exposed ports,
user, env, entrypoint, architectures) to pre-fill the deploy wizard and to
highlight risks. Credentials typed in the wizard are used for this request only
and never stored.
"""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlencode

import httpx

from .errors import BadRequest
from .k8s.diagnostics import parse_image

MANIFEST_TYPES = ", ".join([
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.v2+json",
])  # fmt: skip
INDEX_TYPES = {"application/vnd.oci.image.index.v1+json", "application/vnd.docker.distribution.manifest.list.v2+json"}
_BEARER = re.compile(r'(\w+)="([^"]*)"')
SENSITIVE_ENV = re.compile(r"(PASSWORD|SECRET|TOKEN|PRIVATE_KEY|API_KEY)", re.I)


def _registry_host(registry: str) -> str:
    return "registry-1.docker.io" if registry in ("docker.io", "index.docker.io") else registry


def _repo(registry: str, repository: str) -> str:
    if registry in ("docker.io", "index.docker.io") and "/" not in repository:
        return f"library/{repository}"
    return repository


class RegistryInspector:
    def __init__(self, timeout: float = 10.0, verify_tls: bool = True) -> None:
        self.timeout = timeout
        self.verify_tls = verify_tls

    def _token(self, client: httpx.Client, challenge: str, auth: tuple[str, str] | None) -> str | None:
        if not challenge.lower().startswith("bearer"):
            return None
        params = dict(_BEARER.findall(challenge))
        realm = params.pop("realm", None)
        if not realm or not realm.startswith("https://"):
            return None
        resp = client.get(f"{realm}?{urlencode(params)}", auth=auth)
        if resp.status_code != 200:
            return None
        data = resp.json()
        return data.get("token") or data.get("access_token")

    def inspect(self, image: str, *, username: str | None = None, password: str | None = None) -> dict[str, Any]:
        ref = parse_image(image)
        result: dict[str, Any] = {"image": image, "reference": ref, "checks": [], "config": None, "risks": []}
        checks = result["checks"]
        if not ref.get("valid"):
            checks.append({"id": "image_format", "status": "fail"})
            return result
        checks.append({"id": "image_format", "status": "ok"})
        registry = ref["registry"]
        host = _registry_host(registry)
        repo = _repo(registry, ref["repository"])
        tag = ref.get("digest") or ref.get("tag") or "latest"
        if (not ref.get("tag") and not ref.get("digest")) or ref.get("tag") == "latest":
            result["risks"].append({"level": "medium", "code": "latest_tag"})
        auth = (username, password) if username and password else None
        # HTTPS only, also for redirects (blob downloads are often redirected to object storage):
        # the inspector must not become a way to make the PKM host call internal plain-HTTP services.
        base = f"https://{host}/v2/{repo}"

        def https_only(request: httpx.Request) -> None:
            if request.url.scheme != "https":
                raise httpx.UnsupportedProtocol(f"refusing non-HTTPS URL {request.url}")

        try:
            with httpx.Client(timeout=self.timeout, verify=self.verify_tls, follow_redirects=True, max_redirects=5,
                              event_hooks={"request": [https_only]}) as client:  # fmt: skip
                headers = {"Accept": MANIFEST_TYPES}
                resp = client.get(f"{base}/manifests/{tag}", headers=headers)
                needs_auth = False
                if resp.status_code == 401:
                    needs_auth = True
                    token = self._token(client, resp.headers.get("www-authenticate", ""), auth)
                    if token:
                        headers["Authorization"] = f"Bearer {token}"
                    elif auth:
                        client.auth = httpx.BasicAuth(*auth)
                    resp = client.get(f"{base}/manifests/{tag}", headers=headers)
                checks.append({"id": "registry_reachable", "status": "ok", "params": {"registry": registry}})
                if resp.status_code in (401, 403):
                    checks.append({"id": "registry_auth", "status": "fail",
                                   "params": {"registry": registry, "credentialsProvided": bool(auth)}})  # fmt: skip
                    return result
                checks.append({"id": "registry_auth", "status": "ok",
                               "params": {"registry": registry, "private": needs_auth and bool(auth)}})  # fmt: skip
                if resp.status_code == 404:
                    checks.append({"id": "tag_exists", "status": "fail", "params": {"tag": tag}})
                    return result
                if resp.status_code >= 400:
                    checks.append({"id": "tag_exists", "status": "unknown",
                                   "params": {"tag": tag, "status": resp.status_code}})  # fmt: skip
                    return result
                checks.append({"id": "tag_exists", "status": "ok", "params": {"tag": tag}})
                manifest = resp.json()
                media = resp.headers.get("content-type", "").split(";")[0] or manifest.get("mediaType", "")
                result["digest"] = resp.headers.get("docker-content-digest")
                platforms: list[str] = []
                if media in INDEX_TYPES or "manifests" in manifest:
                    entries = manifest.get("manifests") or []
                    platforms = sorted({f"{(m.get('platform') or {}).get('os')}/{(m.get('platform') or {}).get('architecture')}"
                                        for m in entries if m.get("platform")})  # fmt: skip
                    target = next((m for m in entries if (m.get("platform") or {}).get("os") == "linux"
                                   and (m.get("platform") or {}).get("architecture") == "amd64"), None)  # fmt: skip
                    checks.append({"id": "platform_amd64", "status": "ok" if target else "fail",
                                   "params": {"platforms": platforms}})  # fmt: skip
                    if target is None:
                        return result
                    resp = client.get(f"{base}/manifests/{target['digest']}", headers=headers)
                    resp.raise_for_status()
                    manifest = resp.json()
                layers = manifest.get("layers") or []
                result["size"] = sum(int(layer.get("size", 0)) for layer in layers)
                result["layers"] = len(layers)
                cfg_digest = (manifest.get("config") or {}).get("digest")
                if cfg_digest:
                    blob = client.get(f"{base}/blobs/{cfg_digest}", headers={k: v for k, v in headers.items()
                                                                              if k == "Authorization"})  # fmt: skip
                    blob.raise_for_status()
                    cfg = json.loads(blob.content)
                    arch = cfg.get("architecture")
                    if not platforms:
                        platforms = [f"{cfg.get('os')}/{arch}"]
                        checks.append({"id": "platform_amd64", "status": "ok" if arch == "amd64" else "fail",
                                       "params": {"platforms": platforms}})  # fmt: skip
                    result["config"] = describe_config(cfg)
                    result["risks"] += config_risks(result["config"])
                result["platforms"] = platforms
        except httpx.TimeoutException as exc:
            checks.append({"id": "registry_reachable", "status": "fail",
                           "params": {"registry": registry, "error": f"timeout: {exc}"}})  # fmt: skip
        except (httpx.TransportError, OSError) as exc:
            checks.append({"id": "registry_reachable", "status": "fail",
                           "params": {"registry": registry, "error": f"{type(exc).__name__}: {exc}"}})  # fmt: skip
        except (httpx.HTTPStatusError, ValueError, KeyError) as exc:
            checks.append({"id": "manifest_readable", "status": "fail", "params": {"error": str(exc)[:300]}})
        return result


def describe_config(cfg: dict[str, Any]) -> dict[str, Any]:
    c = cfg.get("config") or cfg.get("Config") or {}
    ports = []
    for p in (c.get("ExposedPorts") or {}):
        num, _, proto = p.partition("/")
        if num.isdigit():
            ports.append({"port": int(num), "protocol": (proto or "tcp").upper()})
    env = []
    for e in c.get("Env") or []:
        k, _, v = e.partition("=")
        env.append({"name": k, "value": "<hidden>" if SENSITIVE_ENV.search(k) else v})
    user = c.get("User") or ""
    return {
        "architecture": cfg.get("architecture") or cfg.get("Architecture"),
        "os": cfg.get("os") or cfg.get("Os"),
        "created": cfg.get("created") or cfg.get("Created"),
        "user": user,
        "runsAsRoot": user in ("", "0", "root") or user.startswith(("0:", "root:")),
        "exposedPorts": sorted(ports, key=lambda p: p["port"]),
        "env": env,
        "entrypoint": c.get("Entrypoint") or [],
        "cmd": c.get("Cmd") or [],
        "workingDir": c.get("WorkingDir") or "",
        "volumes": sorted((c.get("Volumes") or {}).keys()),
        "labels": c.get("Labels") or {},
        "healthcheck": (c.get("Healthcheck") or {}).get("Test"),
    }


def config_risks(desc: dict[str, Any]) -> list[dict[str, Any]]:
    risks = []
    if desc.get("runsAsRoot"):
        risks.append({"level": "medium", "code": "runs_as_root"})
    if not desc.get("exposedPorts"):
        risks.append({"level": "low", "code": "no_exposed_ports"})
    if desc.get("volumes"):
        risks.append({"level": "low", "code": "declares_volumes", "params": {"volumes": desc["volumes"]}})
    if any(e["value"] == "<hidden>" for e in desc.get("env") or []):
        risks.append({"level": "high", "code": "secret_in_image_env"})
    return risks


def podman_image_config(inspect: dict[str, Any]) -> dict[str, Any]:
    """Same description from a local Podman image inspect (images already pulled on the host)."""
    if not inspect:
        raise BadRequest("empty image inspect")
    cfg = {"architecture": inspect.get("Architecture"), "os": inspect.get("Os"), "created": inspect.get("Created"),
           "config": inspect.get("Config") or {}}  # fmt: skip
    return describe_config(cfg)


def demo_inspect(image: str) -> dict[str, Any]:
    """Deterministic result for DEMO mode (no network access)."""
    ref = parse_image(image)
    result: dict[str, Any] = {"image": image, "reference": ref, "checks": [], "config": None, "risks": [], "demo": True}
    if not ref.get("valid"):
        result["checks"].append({"id": "image_format", "status": "fail"})
        return result
    checks = result["checks"]
    checks += [{"id": "image_format", "status": "ok"},
               {"id": "registry_reachable", "status": "ok", "params": {"registry": ref["registry"]}},
               {"id": "registry_auth", "status": "ok", "params": {"registry": ref["registry"]}}]  # fmt: skip
    if "notfound" in image or (ref.get("tag") or "").endswith("-rc1"):
        checks.append({"id": "tag_exists", "status": "fail", "params": {"tag": ref.get("tag")}})
        return result
    checks.append({"id": "tag_exists", "status": "ok", "params": {"tag": ref.get("tag") or "latest"}})
    checks.append({"id": "platform_amd64", "status": "ok", "params": {"platforms": ["linux/amd64", "linux/arm64"]}})
    nginx = "nginx" in ref["repository"]
    cfg = {"architecture": "amd64", "os": "linux", "created": "2026-09-01T10:00:00Z",
           "config": {"ExposedPorts": {"80/tcp" if nginx else "8080/tcp": {}}, "User": "" if nginx else "1001",
                      "Env": ["PATH=/usr/local/bin:/usr/bin", "APP_ENV=production"],
                      "Entrypoint": ["/docker-entrypoint.sh"] if nginx else ["/app/server"],
                      "Cmd": ["nginx", "-g", "daemon off;"] if nginx else [], "WorkingDir": "/app"}}  # fmt: skip
    result["config"] = describe_config(cfg)
    result["risks"] += config_risks(result["config"])
    if not ref.get("tag") or ref.get("tag") == "latest":
        result["risks"].append({"level": "medium", "code": "latest_tag"})
    result.update(size=72_000_000, layers=7, platforms=["linux/amd64", "linux/arm64"], digest="sha256:" + "d" * 64)
    return result
