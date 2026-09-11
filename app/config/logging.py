"""Structured (JSON) logging with request/operation correlation and secret redaction."""

from __future__ import annotations

import contextvars
import json
import logging
import re
import sys
from datetime import UTC, datetime
from typing import Any

log_context: contextvars.ContextVar[dict[str, Any]] = contextvars.ContextVar(
    "scarlet_log_context", default={}
)

CONTEXT_KEYS = (
    "request_id",
    "user_id",
    "target_id",
    "application_id",
    "deployment_id",
    "operation_id",
    "job_id",
)

_PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S
)
_KV_SECRET_RE = re.compile(
    r"(?i)(password|passwd|passphrase|secret|token|api[_-]?key)(\s*[=:]\s*)([^\s,;'\"]+)"
)
_BEARER_RE = re.compile(r"(?i)(authorization:\s*bearer\s+)([A-Za-z0-9\-_.=]+)")


def redact(text: str) -> str:
    """Remove obviously secret material from free text before it is logged/stored."""
    if not text:
        return text
    out = _PRIVATE_KEY_RE.sub("[REDACTED PRIVATE KEY]", text)
    out = _KV_SECRET_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}[REDACTED]", out)
    out = _BEARER_RE.sub(lambda m: f"{m.group(1)}[REDACTED]", out)
    return out


def bind_context(**kwargs: Any) -> contextvars.Token:
    current = dict(log_context.get())
    current.update({k: v for k, v in kwargs.items() if v is not None})
    return log_context.set(current)


def reset_context(token: contextvars.Token | None = None) -> None:
    if token is not None:
        log_context.reset(token)
    else:
        log_context.set({})


def current_context() -> dict[str, Any]:
    return dict(log_context.get())


class ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        ctx = log_context.get()
        for key in CONTEXT_KEYS:
            if not hasattr(record, key):
                setattr(record, key, ctx.get(key))
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact(record.getMessage()),
        }
        for key in CONTEXT_KEYS:
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        extra = getattr(record, "extra_data", None)
        if isinstance(extra, dict):
            payload.update({k: v for k, v in extra.items() if k not in payload})
        if record.exc_info:
            payload["exception"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, default=str)


class TextFormatter(logging.Formatter):
    def __init__(self) -> None:
        super().__init__(
            "%(asctime)s %(levelname)-7s %(name)s [req=%(request_id)s] %(message)s"
        )

    def format(self, record: logging.LogRecord) -> str:
        record.msg = redact(str(record.msg))
        return super().format(record)


def configure_logging(level: str = "INFO", fmt: str = "json") -> None:
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter() if fmt == "json" else TextFormatter())
    handler.addFilter(ContextFilter())
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    for noisy in ("paramiko", "werkzeug", "kubernetes", "urllib3", "celery.utils.functional"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
