"""Live Kubernetes provider.

The official Python client is used only to load credentials (kubeconfig, in-cluster
service account, client certificates, exec/OIDC token plugins). Requests go straight
to known REST paths (see kinds.py) through urllib3: no API discovery round-trips,
raw JSON in and out, explicit timeouts on every call and no dependency on the
client's generated request layer, which changes between client releases.
"""

from __future__ import annotations

import json
import logging
import ssl
import threading
import time
from collections.abc import Iterator
from typing import Any
from urllib.parse import quote, urlencode, urlparse

import urllib3
from kubernetes import client, config
from kubernetes.config.config_exception import ConfigException

from ..config import KubernetesConfig
from ..errors import (
    AppError,
    K8sAuthFailed,
    K8sConflict,
    K8sForbidden,
    K8sInvalid,
    K8sNotConfigured,
    K8sNotFound,
    K8sTimeout,
    K8sUnavailable,
)
from .kinds import BY_KIND
from .provider import KubernetesProvider, LogStream

log = logging.getLogger("pkm.k8s")

FIELD_MANAGER = "pkm"

_PATCH_TYPES = {
    "merge": "application/merge-patch+json",
    "strategic": "application/strategic-merge-patch+json",
    "json": "application/json-patch+json",
}


def _status_message(status: int, body_text: str, reason: str | None) -> tuple[str, dict[str, Any]]:
    try:
        body = json.loads(body_text or "{}")
    except (TypeError, ValueError):
        body = {}
    if not isinstance(body, dict):
        body = {}
    msg = body.get("message") or reason or (body_text or "")[:300] or "Kubernetes API error"
    params: dict[str, Any] = {"status": status, "reason": body.get("reason")}
    causes = (body.get("details") or {}).get("causes")
    if causes:
        params["causes"] = [{"field": c.get("field"), "message": c.get("message")} for c in causes][:20]
    return msg, params


def map_api_error(status: int, body_text: str, reason: str | None = None) -> AppError:
    msg, params = _status_message(status, body_text, reason)
    if status == 401:
        return K8sAuthFailed("Kubernetes rejected the credentials", details=msg, params=params)
    if status == 403:
        return K8sForbidden("the Kubernetes account used by PKM is not allowed to do this", details=msg,
                            params=params)  # fmt: skip
    if status == 404:
        return K8sNotFound(msg, details=msg, params=params)
    if status == 409:
        return K8sConflict(msg, details=msg, params=params)
    if status in (400, 422):
        return K8sInvalid(msg, details=msg, params=params)
    if status in (408, 504):
        return K8sTimeout("Kubernetes API timed out", details=msg, params=params)
    return K8sUnavailable(f"Kubernetes API error ({status})", details=msg, params=params)


def map_transport_exception(exc: Exception) -> AppError:
    text = f"{type(exc).__name__}: {exc}"
    reason = exc.reason if isinstance(exc, urllib3.exceptions.MaxRetryError) else exc
    # A connect timeout means the API server cannot be reached; a read timeout means it is slow.
    if isinstance(reason, urllib3.exceptions.ConnectTimeoutError):
        return K8sUnavailable("cannot reach the Kubernetes API", details=text, params={"reason": "connect_timeout"})
    if isinstance(reason, urllib3.exceptions.ReadTimeoutError):
        return K8sTimeout("Kubernetes API did not answer in time", details=text)
    if isinstance(exc, urllib3.exceptions.SSLError) or (
        isinstance(exc, urllib3.exceptions.MaxRetryError) and isinstance(exc.reason, urllib3.exceptions.SSLError)
    ):
        return K8sUnavailable("TLS error talking to the Kubernetes API", details=text, params={"reason": "tls"})
    if isinstance(exc, ConfigException):
        return K8sAuthFailed("Kubernetes credentials could not be obtained", details=text)
    return K8sUnavailable("cannot reach the Kubernetes API", details=text)


_TRANSPORT_ERRORS = (urllib3.exceptions.HTTPError, OSError, ConfigException)


class _UrllibLogStream(LogStream):
    """Follows pod logs; reconnects with sinceTime after read timeouts, deduplicating lines."""

    def __init__(self, opener: Any, *, tail_lines: int | None, since_time: str | None) -> None:
        self._opener = opener
        self._tail = tail_lines
        self._since = since_time
        self._closed = threading.Event()
        self._resp: Any = None

    def __iter__(self) -> Iterator[str]:
        last_ts: str | None = None
        seen_at_last: set[str] = set()
        first = True
        reconnects = 0
        while not self._closed.is_set():
            try:
                self._resp = self._opener(
                    tail_lines=self._tail if first else None, since_time=self._since if first else last_ts
                )
            except AppError:
                if first:
                    raise
                return
            first = False
            buf = b""
            try:
                for chunk in self._resp.stream(4096, decode_content=True):
                    if self._closed.is_set():
                        return
                    buf += chunk
                    while b"\n" in buf:
                        raw, buf = buf.split(b"\n", 1)
                        line = raw.decode("utf-8", errors="replace").rstrip("\r")
                        ts = line.split(" ", 1)[0]
                        if last_ts is not None and ts < last_ts:
                            continue
                        if ts == last_ts:
                            if line in seen_at_last:
                                continue
                        else:
                            seen_at_last = set()
                        last_ts = ts
                        seen_at_last.add(line)
                        yield line
                # Server closed the stream (container ended): stop following.
                return
            except _TRANSPORT_ERRORS:
                if self._closed.is_set():
                    return
                reconnects += 1
                if reconnects > 100 or last_ts is None:
                    return
                time.sleep(0.5)
            finally:
                self._release()

    def _release(self) -> None:
        resp, self._resp = self._resp, None
        if resp is not None:
            try:
                resp.release_conn()
                resp.close()
            except Exception:  # noqa: S110 - best effort cleanup
                pass

    def close(self) -> None:
        self._closed.set()
        self._release()


class LiveKubernetes(KubernetesProvider):
    demo = False

    def __init__(self, cfg: KubernetesConfig) -> None:
        self.cfg = cfg
        self.context_name: str | None = None
        self.server: str | None = None
        self._api: urllib3.PoolManager | None = None
        self._conf: Any = None
        self._init_error: AppError | None = None
        self._version_cache: tuple[float, dict[str, Any]] | None = None
        if not cfg.enabled:
            self._init_error = K8sNotConfigured("Kubernetes integration is disabled in the configuration")
            return
        try:
            self._api = self._build()
        except AppError as exc:
            self._init_error = exc
        except Exception as exc:
            self._init_error = K8sNotConfigured(
                "the Kubernetes connection could not be configured", details=f"{type(exc).__name__}: {exc}"
            )
            log.warning("kubernetes configuration failed", extra={"error": str(exc)})

    def _build(self) -> urllib3.PoolManager:
        conf = client.Configuration()
        if self.cfg.in_cluster:
            config.load_incluster_config(client_configuration=conf)
            self.context_name = "in-cluster"
        else:
            path = self.cfg.kubeconfig
            if not path:
                raise K8sNotConfigured("no kubeconfig file configured", params={"reason": "no_kubeconfig"})
            try:
                contexts, active = config.list_kube_config_contexts(config_file=path)
            except (OSError, ConfigException) as exc:
                raise K8sNotConfigured(
                    "the kubeconfig file cannot be read", details=str(exc), params={"path": path}
                ) from exc
            names = [c["name"] for c in contexts or []]
            if self.cfg.context and self.cfg.context not in names:
                raise K8sNotConfigured(
                    f"context '{self.cfg.context}' not found in kubeconfig",
                    params={"context": self.cfg.context, "available": names},
                )
            config.load_kube_config(
                config_file=path, context=self.cfg.context, client_configuration=conf, persist_config=False
            )
            self.context_name = self.cfg.context or (active or {}).get("name")
        self._conf = conf
        self.server = conf.host.rstrip("/")
        pool_kw: dict[str, Any] = {
            "num_pools": 4,
            "maxsize": 16,
            "cert_reqs": ssl.CERT_REQUIRED if conf.verify_ssl else ssl.CERT_NONE,
            "ca_certs": conf.ssl_ca_cert,
            "cert_file": conf.cert_file,
            "key_file": conf.key_file,
            # Only retry connection establishment, never replay requests.
            "retries": urllib3.Retry(total=1, connect=1, read=0, status=0, redirect=0, backoff_factor=0.3),
        }
        if getattr(conf, "assert_hostname", None) is not None:
            pool_kw["assert_hostname"] = conf.assert_hostname
        if getattr(conf, "tls_server_name", None):
            pool_kw["server_hostname"] = conf.tls_server_name
        if conf.proxy:
            return urllib3.ProxyManager(proxy_url=conf.proxy, proxy_headers=conf.proxy_headers, **pool_kw)
        return urllib3.PoolManager(**pool_kw)

    @property
    def configured(self) -> bool:
        return self._api is not None

    def _auth_headers(self) -> dict[str, str]:
        # get_api_key_with_prefix runs the refresh hook (exec plugins, in-cluster token rotation).
        # The token is stored under "BearerToken" by kubernetes-client >= 35, "authorization" before.
        token = self._conf.get_api_key_with_prefix("BearerToken") or self._conf.get_api_key_with_prefix(
            "authorization"
        )
        if token:
            return {"Authorization": token}
        if self._conf.username and self._conf.password:
            return urllib3.make_headers(basic_auth=f"{self._conf.username}:{self._conf.password}")
        return {}

    def _request(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, Any] | None = None,
        body: Any = None,
        content_type: str | None = None,
        read_timeout: float | None = None,
    ) -> urllib3.BaseHTTPResponse:
        """Perform a request; returns the unread response (status 2xx) or raises an AppError."""
        if self._api is None:
            raise self._init_error or K8sNotConfigured("Kubernetes is not configured")
        url = self.server + quote(path, safe="/:@-._~")
        params = {k: v for k, v in (query or {}).items() if v is not None}
        if params:
            url += "?" + urlencode(params)
        headers = {"Accept": "application/json", "User-Agent": "pkm"}
        payload: bytes | None = None
        if body is not None:
            payload = body.encode() if isinstance(body, str) else json.dumps(body).encode()
            headers["Content-Type"] = content_type or "application/json"
        try:
            headers.update(self._auth_headers())
            resp = self._api.request(
                method,
                url,
                body=payload,
                headers=headers,
                preload_content=False,
                timeout=urllib3.Timeout(connect=self.cfg.connect_timeout,
                                        read=read_timeout or self.cfg.request_timeout),
            )  # fmt: skip
        except _TRANSPORT_ERRORS as exc:
            raise map_transport_exception(exc) from exc
        if not 200 <= resp.status <= 299:
            try:
                text = resp.data.decode("utf-8", errors="replace")
            except _TRANSPORT_ERRORS:
                text = ""
            finally:
                resp.release_conn()
            raise map_api_error(resp.status, text, resp.reason)
        return resp

    def _call(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, Any] | None = None,
        body: Any = None,
        content_type: str | None = None,
        read_timeout: float | None = None,
    ) -> Any:
        resp = self._request(
            method, path, query=query, body=body, content_type=content_type, read_timeout=read_timeout
        )
        try:
            data = resp.data
        except _TRANSPORT_ERRORS as exc:
            raise map_transport_exception(exc) from exc
        finally:
            resp.release_conn()
        if not data:
            return {}
        try:
            return json.loads(data)
        except ValueError as exc:
            raise K8sUnavailable("unexpected response from the Kubernetes API", details=str(exc)) from exc

    # --- info ------------------------------------------------------------------
    def info(self) -> dict[str, Any]:
        base: dict[str, Any] = {
            "connected": False,
            "configured": self.configured,
            "context": self.context_name,
            "server": _safe_server(self.server),
            "version": None,
        }
        if self._api is None:
            err = self._init_error or K8sNotConfigured("not configured")
            return {**base, "error": {"code": err.code, "message": err.message, "details": err.details,
                                      "params": err.params}}  # fmt: skip
        now = time.monotonic()
        if self._version_cache and now - self._version_cache[0] < 30:
            return {**base, "connected": True, "version": self._version_cache[1]}
        try:
            v = self._call("GET", "/version", read_timeout=min(self.cfg.request_timeout, 10))
        except AppError as exc:
            return {**base, "error": {"code": exc.code, "message": exc.message, "details": exc.details,
                                      "params": exc.params}}  # fmt: skip
        version = {k: v.get(k) for k in ("gitVersion", "major", "minor", "platform")}
        self._version_cache = (now, version)
        return {**base, "connected": True, "version": version}

    # --- resources ---------------------------------------------------------------
    def list(self, kind, namespace=None, *, label_selector=None, field_selector=None):
        data = self._call(
            "GET",
            kind.collection_path(namespace),
            query={"labelSelector": label_selector, "fieldSelector": field_selector},
        )
        items = data.get("items") or []
        for it in items:  # list responses omit apiVersion/kind on items
            it.setdefault("apiVersion", kind.api_version)
            it.setdefault("kind", kind.kind)
        return items

    def get(self, kind, name, namespace=None):
        obj = self._call("GET", kind.item_path(name, namespace))
        obj.setdefault("apiVersion", kind.api_version)
        obj.setdefault("kind", kind.kind)
        return obj

    def apply(self, manifest, *, dry_run=False, force=False):
        kind = BY_KIND[manifest["kind"]]
        meta = manifest.get("metadata") or {}
        return self._call(
            "PATCH",
            kind.item_path(meta["name"], meta.get("namespace")),
            query={"fieldManager": FIELD_MANAGER, "force": "true" if force else None,
                   "dryRun": "All" if dry_run else None},
            body=json.dumps(manifest),
            content_type="application/apply-patch+yaml",
        )  # fmt: skip

    def create(self, manifest, *, dry_run=False):
        kind = BY_KIND[manifest["kind"]]
        ns = (manifest.get("metadata") or {}).get("namespace")
        return self._call(
            "POST",
            kind.collection_path(ns),
            query={"fieldManager": FIELD_MANAGER, "dryRun": "All" if dry_run else None},
            body=manifest,
        )

    def patch(self, kind, name, namespace, body, *, patch_type="merge", dry_run=False):
        return self._call(
            "PATCH",
            kind.item_path(name, namespace),
            query={"fieldManager": FIELD_MANAGER, "dryRun": "All" if dry_run else None},
            body=body,
            content_type=_PATCH_TYPES[patch_type],
        )

    def delete(self, kind, name, namespace, *, propagation="Background"):
        return self._call(
            "DELETE",
            kind.item_path(name, namespace),
            body={"kind": "DeleteOptions", "apiVersion": "v1", "propagationPolicy": propagation},
            content_type="application/json",
        )

    # --- logs ------------------------------------------------------------------
    def pod_logs(self, name, namespace, *, container=None, tail_lines=None, since_seconds=None,
                 timestamps=False, previous=False, limit_bytes=None):  # fmt: skip
        # Read the raw body: the client's "str" deserializer would json-decode JSON log lines.
        resp = self._request(
            "GET",
            f"/api/v1/namespaces/{namespace}/pods/{name}/log",
            query={
                "container": container,
                "tailLines": tail_lines,
                "sinceSeconds": since_seconds,
                "timestamps": "true" if timestamps else None,
                "previous": "true" if previous else None,
                "limitBytes": limit_bytes,
            },
            read_timeout=max(self.cfg.request_timeout, 30),
        )
        try:
            return resp.data.decode("utf-8", errors="replace")
        except _TRANSPORT_ERRORS as exc:
            raise map_transport_exception(exc) from exc
        finally:
            resp.release_conn()

    def stream_pod_logs(self, name, namespace, *, container=None, tail_lines=None, since_time=None):
        def opener(tail_lines: int | None, since_time: str | None) -> Any:
            return self._request(
                "GET",
                f"/api/v1/namespaces/{namespace}/pods/{name}/log",
                query={"container": container, "follow": "true", "timestamps": "true",
                       "tailLines": tail_lines, "sinceTime": since_time},
                read_timeout=60,
            )  # fmt: skip

        return _UrllibLogStream(opener, tail_lines=tail_lines, since_time=since_time)

    # --- eviction --------------------------------------------------------------
    def evict(self, name, namespace):
        path = f"/api/v1/namespaces/{namespace}/pods/{name}/eviction"
        body = {"apiVersion": "policy/v1", "kind": "Eviction", "metadata": {"name": name, "namespace": namespace}}
        try:
            self._call("POST", path, body=body, content_type="application/json")
        except K8sInvalid:
            body["apiVersion"] = "policy/v1beta1"  # clusters older than 1.22
            self._call("POST", path, body=body, content_type="application/json")

    # --- metrics ---------------------------------------------------------------
    def _metrics(self, path: str) -> list[dict[str, Any]] | None:
        try:
            data = self._call("GET", path, read_timeout=min(self.cfg.request_timeout, 10))
        except (K8sNotFound, K8sUnavailable, K8sForbidden, K8sTimeout):
            return None
        return data.get("items") or []

    def node_metrics(self):
        return self._metrics("/apis/metrics.k8s.io/v1beta1/nodes")

    def pod_metrics(self, namespace=None):
        if namespace:
            return self._metrics(f"/apis/metrics.k8s.io/v1beta1/namespaces/{namespace}/pods")
        return self._metrics("/apis/metrics.k8s.io/v1beta1/pods")

    def close(self) -> None:
        if self._api is not None:
            try:
                self._api.clear()
            except Exception:  # noqa: S110
                pass


def _safe_server(server: str | None) -> str | None:
    if not server:
        return None
    u = urlparse(server)
    return f"{u.scheme}://{u.hostname}{':' + str(u.port) if u.port else ''}"
