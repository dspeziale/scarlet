"""Log strutturati su stdout: una riga JSON per evento.

Nessun file di log dentro il container: Docker raccoglie stdout/stderr e ``appctl logs``
li rende disponibili agli operatori.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "time": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        for key in ("method", "path", "status", "duration_ms", "client"):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: str = "INFO", fmt: str = "json") -> None:
    handler = logging.StreamHandler(sys.stdout)
    if fmt == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())

    # uvicorn ha i propri logger: li facciamo confluire nel root (stesso formato).
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers.clear()
        lg.propagate = True
    # L'access log di uvicorn e' sostituito dal middleware applicativo (piu' informativo).
    logging.getLogger("uvicorn.access").disabled = True
