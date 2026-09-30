"""Schemi Pydantic delle API."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

NAME_RE = r"^[a-z][a-z0-9-]{1,31}$"


class DeploymentIn(BaseModel):
    application: str = Field(pattern=NAME_RE, examples=["scarlet"])
    environment: Literal["development", "production"]
    version: str = Field(min_length=1, max_length=64)
    image: str = Field(min_length=1, max_length=255)
    commit: str | None = Field(default=None, max_length=64)
    actor: str = Field(min_length=1, max_length=128)
    result: Literal["success", "failed", "rolled-back"] = "success"
    repository: str | None = Field(default=None, max_length=255)

    @field_validator("version", "image", "actor")
    @classmethod
    def _no_control_chars(cls, value: str) -> str:
        if any(ord(c) < 32 for c in value):
            raise ValueError("caratteri di controllo non ammessi")
        return value


class DeploymentOut(BaseModel):
    id: int
    application: str
    environment: str
    version: str
    image: str
    commit: str | None
    actor: str
    result: str
    deployed_at: datetime


class ApplicationOut(BaseModel):
    name: str
    repository: str | None
    current: dict[str, DeploymentOut]
