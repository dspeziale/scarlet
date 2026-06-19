"""
Watches the PCAP directory for completed capture files and uploads them
to the server via multipart POST.

Suricata writes PCAP files with a timestamp suffix.  We treat a file as
"complete" when it has not been modified for STABLE_SECONDS (default 5 s),
which avoids uploading a file Suricata is still writing.
"""

from __future__ import annotations

import hashlib
import os
import threading
import time
from pathlib import Path

import httpx
import structlog

from local_queue import LocalQueue

log = structlog.get_logger(__name__)

STABLE_SECONDS = 5
CHUNK_SIZE = 1 << 16  # 64 KB


class PcapUploader(threading.Thread):
    def __init__(
        self,
        server_url: str,
        probe_id: str,
        pcap_dir: Path,
        http_client: httpx.Client,
        queue: LocalQueue,
        scan_interval: int = 10,
    ) -> None:
        super().__init__(name="pcap-uploader", daemon=True)
        self._url = f"{server_url}/api/v1/probes/{probe_id}/pcap"
        self._pcap_dir = pcap_dir
        self._http = http_client
        self._queue = queue
        self._scan_interval = scan_interval
        self._uploaded: set[str] = set()
        self._stop = threading.Event()

    def run(self) -> None:
        self._pcap_dir.mkdir(parents=True, exist_ok=True)
        log.info("pcap_uploader_started", pcap_dir=str(self._pcap_dir))
        self._replay_queued()
        while not self._stop.is_set():
            try:
                self._scan_and_upload()
            except Exception:
                log.exception("pcap_uploader_error")
            self._stop.wait(self._scan_interval)

    def shutdown(self) -> None:
        self._stop.set()

    # ── Scan ─────────────────────────────────────────────────────────────

    def _scan_and_upload(self) -> None:
        now = time.time()
        for path in sorted(self._pcap_dir.glob("*.pcap")):
            if str(path) in self._uploaded:
                continue
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            if now - mtime < STABLE_SECONDS:
                continue  # Still being written
            self._upload(path)

    def _upload(self, path: Path) -> None:
        sha256 = _sha256(path)
        size = path.stat().st_size
        log.info("pcap_uploading", file=path.name, size=size, sha256=sha256[:16])
        try:
            with open(path, "rb") as fh:
                resp = self._http.post(
                    self._url,
                    files={"file": (path.name, fh, "application/vnd.tcpdump.pcap")},
                    data={"sha256": sha256, "original_name": path.name},
                    timeout=120,
                )
            resp.raise_for_status()
            self._uploaded.add(str(path))
            log.info("pcap_uploaded", file=path.name)
            path.unlink(missing_ok=True)
        except Exception as exc:
            log.warning("pcap_upload_failed", file=path.name, error=str(exc))
            self._queue.push("pcap_meta", {"path": str(path), "sha256": sha256})

    # ── Replay ───────────────────────────────────────────────────────────

    def _replay_queued(self) -> None:
        items = self._queue.peek("pcap_meta", limit=20)
        if not items:
            return
        log.info("replaying_queued_pcap", count=len(items))
        for row_id, meta in items:
            p = Path(meta["path"])
            if not p.exists():
                self._queue.ack([row_id])
                continue
            try:
                with open(p, "rb") as fh:
                    resp = self._http.post(
                        self._url,
                        files={"file": (p.name, fh, "application/vnd.tcpdump.pcap")},
                        data={"sha256": meta.get("sha256", ""), "original_name": p.name},
                        timeout=120,
                    )
                resp.raise_for_status()
                self._queue.ack([row_id])
                self._uploaded.add(str(p))
                p.unlink(missing_ok=True)
                log.info("pcap_replay_ok", file=p.name)
            except Exception as exc:
                log.warning("pcap_replay_failed", file=p.name, error=str(exc))
                self._queue.increment_retry(row_id)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(CHUNK_SIZE), b""):
            h.update(chunk)
    return h.hexdigest()
