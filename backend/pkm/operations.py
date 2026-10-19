"""Long-running operations (node drain, backup) executed in background threads with progress tracking."""

from __future__ import annotations

import logging
import threading
import uuid
from collections.abc import Callable
from typing import Any

from .db import iso
from .errors import AppError, NotFound

log = logging.getLogger("pkm.operations")
MAX_KEEP = 100


class Operation:
    def __init__(self, kind: str, target: str, user: str) -> None:
        self.id = uuid.uuid4().hex[:16]
        self.kind = kind
        self.target = target
        self.user = user
        self.status = "running"
        self.started_at = iso()
        self.finished_at: str | None = None
        self.steps: list[dict[str, Any]] = []
        self.result: Any = None
        self.error: dict[str, Any] | None = None
        self._cancel = threading.Event()

    def progress(self, step: str, data: dict[str, Any] | None = None) -> None:
        self.steps.append({"ts": iso(), "step": step, **(data or {})})
        del self.steps[:-500]

    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def public(self) -> dict[str, Any]:
        return {"id": self.id, "kind": self.kind, "target": self.target, "user": self.user, "status": self.status,
                "startedAt": self.started_at, "finishedAt": self.finished_at, "steps": self.steps,
                "result": self.result, "error": self.error}  # fmt: skip


class OperationManager:
    def __init__(self) -> None:
        self._ops: dict[str, Operation] = {}
        self._lock = threading.Lock()

    def start(self, kind: str, target: str, user: str, fn: Callable[[Operation], Any],
              on_done: Callable[[Operation], None] | None = None) -> Operation:  # fmt: skip
        with self._lock:
            for op in self._ops.values():
                if op.kind == kind and op.target == target and op.status == "running":
                    from .errors import Conflict

                    raise Conflict(f"a {kind} operation on {target} is already running", params={"operation": op.id})
            op = Operation(kind, target, user)
            self._ops[op.id] = op
            if len(self._ops) > MAX_KEEP:
                for old in sorted(self._ops.values(), key=lambda o: o.started_at)[: len(self._ops) - MAX_KEEP]:
                    if old.status != "running":
                        self._ops.pop(old.id, None)

        def run() -> None:
            try:
                op.result = fn(op)
                op.status = "cancelled" if op.cancelled() else "succeeded"
            except AppError as exc:
                op.status = "failed"
                op.error = {"code": exc.code, "message": exc.message, "params": exc.params, "details": exc.details}
            except Exception as exc:
                log.exception("operation failed", extra={"operation": op.id, "kind": kind})
                op.status = "failed"
                op.error = {"code": "internal_error", "message": str(exc)}
            finally:
                op.finished_at = iso()
                if on_done:
                    try:
                        on_done(op)
                    except Exception:
                        log.exception("operation completion hook failed")

        threading.Thread(target=run, name=f"op-{kind}-{op.id}", daemon=True).start()
        return op

    def get(self, op_id: str) -> Operation:
        op = self._ops.get(op_id)
        if op is None:
            raise NotFound("operation not found")
        return op

    def cancel(self, op_id: str) -> Operation:
        op = self.get(op_id)
        op._cancel.set()
        return op

    def list(self) -> list[dict[str, Any]]:
        return [o.public() for o in sorted(self._ops.values(), key=lambda o: o.started_at, reverse=True)]

    def cancel_all(self) -> None:
        for op in self._ops.values():
            op._cancel.set()
