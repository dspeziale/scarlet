"""Stato dei deployment: current.json, previous.json, history.jsonl e lock esclusivo."""

from __future__ import annotations

import json
import os
import socket
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from appctl.errors import LockedError

try:  # Linux (server)
    import fcntl
except ImportError:  # Windows (solo sviluppo/test)
    fcntl = None  # type: ignore[assignment]


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def fmt_ts(value: str | None) -> str:
    """Rende leggibile un timestamp ISO (anche quelli di Docker con nanosecondi)."""
    if not value or value.startswith("0001-"):
        return "-"
    try:
        cleaned = value.replace("Z", "+00:00")
        if "." in cleaned:
            head, _, tail = cleaned.partition(".")
            frac = ""
            tz = ""
            for i, ch in enumerate(tail):
                if ch in "+-":
                    frac, tz = tail[:i], tail[i:]
                    break
            else:
                frac = tail
            cleaned = f"{head}.{frac[:6].ljust(6, '0')}{tz}"
        dt = datetime.fromisoformat(cleaned)
        return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return value


@dataclass
class DeploymentRecord:
    application: str
    environment: str
    image: str
    tag: str
    commit: str = "unknown"
    version: str = "unknown"
    digest: str = ""
    actor: str = "unknown"
    timestamp: str = field(default_factory=now_iso)
    action: str = "deploy"  # deploy | rollback
    result: str = "started"  # started | success | failed | rolled-back
    detail: str = ""
    duration_s: float | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> DeploymentRecord:
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**known)


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


class StateStore:
    def __init__(self, state_dir: Path):
        self.state_dir = state_dir
        self.current_file = state_dir / "current.json"
        self.previous_file = state_dir / "previous.json"
        self.history_file = state_dir / "history.jsonl"
        self.lock_file = state_dir / ".lock"
        self._lock_fh = None

    def ensure(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ current/previous
    def _read(self, path: Path) -> DeploymentRecord | None:
        if not path.is_file():
            return None
        try:
            return DeploymentRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, TypeError):
            return None

    def current(self) -> DeploymentRecord | None:
        return self._read(self.current_file)

    def previous(self) -> DeploymentRecord | None:
        return self._read(self.previous_file)

    def set_current(self, record: DeploymentRecord) -> None:
        """Promuove record a corrente; il corrente precedente (se di tag diverso) diventa previous."""
        self.ensure()
        old = self.current()
        if old and old.tag != record.tag:
            _atomic_write(self.previous_file, json.dumps(old.to_dict(), indent=2))
        _atomic_write(self.current_file, json.dumps(record.to_dict(), indent=2))

    # ------------------------------------------------------------------ history
    def append_history(self, record: DeploymentRecord) -> None:
        self.ensure()
        with self.history_file.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")

    def history(self, limit: int = 20) -> list[DeploymentRecord]:
        if not self.history_file.is_file():
            return []
        rows: list[DeploymentRecord] = []
        for line in self.history_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(DeploymentRecord.from_dict(json.loads(line)))
            except (json.JSONDecodeError, TypeError):
                continue
        return rows[-limit:]

    # ------------------------------------------------------------------ lock
    def acquire_lock(self, holder: str) -> None:
        self.ensure()
        fh = self.lock_file.open("a+", encoding="utf-8")
        if fcntl is not None:
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                fh.seek(0)
                who = fh.read().strip() or "sconosciuto"
                fh.close()
                raise LockedError(who) from None
        else:  # Windows: lock cooperativo tramite contenuto (solo sviluppo)
            fh.seek(0)
            content = fh.read().strip()
            if content and self._pid_alive(content):
                fh.close()
                raise LockedError(content)
        fh.seek(0)
        fh.truncate()
        fh.write(f"{holder} pid={os.getpid()} host={socket.gethostname()} at={now_iso()}")
        fh.flush()
        self._lock_fh = fh

    @staticmethod
    def _pid_alive(content: str) -> bool:
        for part in content.split():
            if part.startswith("pid="):
                try:
                    os.kill(int(part[4:]), 0)
                    return True
                except (OSError, ValueError):
                    return False
        return False

    def release_lock(self) -> None:
        if self._lock_fh is None:
            return
        try:
            self._lock_fh.seek(0)
            self._lock_fh.truncate()
            if fcntl is not None:
                fcntl.flock(self._lock_fh.fileno(), fcntl.LOCK_UN)
        finally:
            self._lock_fh.close()
            self._lock_fh = None
