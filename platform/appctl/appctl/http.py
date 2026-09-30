"""Probe HTTP minimale (urllib) per health, ready, version e connettivita' registry."""

from __future__ import annotations

import json
import socket
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass
class Probe:
    status: int  # 0 = nessuna risposta
    body: dict | None
    error: str = ""

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300


class HttpProber:
    def get(self, url: str, timeout: float = 3.0) -> Probe:
        if not url.startswith(("http://", "https://")):
            return Probe(0, None, "schema URL non supportato")
        req = urllib.request.Request(url, headers={"User-Agent": "appctl"})  # noqa: S310
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - URL locali/config
                raw = resp.read(65536)
                status = resp.status
        except urllib.error.HTTPError as exc:
            raw = exc.read(65536) if exc.fp else b""
            status = exc.code
        except (TimeoutError, urllib.error.URLError, OSError, ValueError) as exc:
            return Probe(0, None, str(exc)[:200])
        body: dict | None
        try:
            parsed = json.loads(raw.decode("utf-8")) if raw else None
            body = parsed if isinstance(parsed, dict) else None
        except (json.JSONDecodeError, UnicodeDecodeError):
            body = None
        return Probe(status, body)

    def tls_days_left(self, host: str, port: int = 443, timeout: float = 5.0) -> int | None:
        ctx = ssl.create_default_context()
        try:
            with (
                socket.create_connection((host, port), timeout=timeout) as sock,
                ctx.wrap_socket(sock, server_hostname=host) as tls,
            ):
                cert = tls.getpeercert()
        except (OSError, ssl.SSLError):
            return None
        not_after = cert.get("notAfter") if cert else None
        if not not_after:
            return None
        expires = datetime.strptime(not_after, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=UTC)
        return (expires - datetime.now(UTC)).days
