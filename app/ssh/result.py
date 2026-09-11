"""Result of a remote command execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.errors import RemoteCommandError

MAX_CAPTURE = 512 * 1024  # bytes kept per stream


def truncate_output(text: str, limit: int = MAX_CAPTURE) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... [truncated {len(text) - limit} characters]"


@dataclass
class CommandResult:
    command: str
    exit_code: int
    stdout: str
    stderr: str
    started_at: datetime
    completed_at: datetime
    duration_seconds: float
    timed_out: bool = False
    command_type: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out

    def raise_for_status(self, message: str | None = None) -> CommandResult:
        if not self.ok:
            raise RemoteCommandError(
                message or f"Remote command failed with exit code {self.exit_code}.",
                exit_code=self.exit_code,
                stdout=self.stdout,
                stderr=self.stderr,
                details={"command": self.command, "timed_out": self.timed_out},
            )
        return self

    def to_dict(self) -> dict[str, Any]:
        return {
            "command": self.command,
            "command_type": self.command_type,
            "exit_code": self.exit_code,
            "stdout": truncate_output(self.stdout),
            "stderr": truncate_output(self.stderr),
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat(),
            "duration_seconds": self.duration_seconds,
            "timed_out": self.timed_out,
        }
