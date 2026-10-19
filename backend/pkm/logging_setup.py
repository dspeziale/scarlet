"""Structured logging: JSON lines with timestamp, level, component, message and request id."""

from __future__ import annotations

import contextvars
import json
import logging
import logging.handlers
import sys
from datetime import UTC, datetime
from pathlib import Path

from .config import LoggingConfig

request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)

_RESERVED = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "component": record.name,
            "message": record.getMessage(),
        }
        rid = request_id_var.get()
        if rid:
            payload["request_id"] = rid
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value if isinstance(value, (str, int, float, bool, type(None))) else str(value)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


class TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        rid = request_id_var.get()
        base = (
            f"{datetime.fromtimestamp(record.created, tz=UTC).isoformat(timespec='seconds')} "
            f"{record.levelname:<7} {record.name}: {record.getMessage()}"
        )
        extras = " ".join(f"{k}={v}" for k, v in record.__dict__.items() if k not in _RESERVED and not k.startswith("_"))
        if extras:
            base += f" {extras}"
        if rid:
            base += f" [rid={rid}]"
        if record.exc_info:
            base += "\n" + self.formatException(record.exc_info)
        return base


def setup_logging(cfg: LoggingConfig) -> None:
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    fmt: logging.Formatter = JsonFormatter() if cfg.json_format else TextFormatter()
    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(fmt)
    root.addHandler(stream)
    if cfg.file:
        Path(cfg.file).parent.mkdir(parents=True, exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(
            cfg.file, maxBytes=cfg.max_bytes, backupCount=cfg.backup_count, encoding="utf-8"
        )
        fh.setFormatter(JsonFormatter())
        root.addHandler(fh)
    set_level(cfg.level)
    # Libraries are noisy at DEBUG/INFO.
    for noisy in ("urllib3", "kubernetes", "httpx", "httpcore", "uvicorn.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def set_level(level: str) -> None:
    logging.getLogger().setLevel(level)
    logging.getLogger("pkm").setLevel(level)
