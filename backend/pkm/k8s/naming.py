"""Kubernetes name validation (DNS-1123)."""

from __future__ import annotations

import re

from ..errors import ValidationFailed

DNS1123_LABEL = re.compile(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")
DNS1123_SUBDOMAIN = re.compile(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?(\.[a-z0-9]([-a-z0-9]*[a-z0-9])?)*$")
LABEL_VALUE = re.compile(r"^(([A-Za-z0-9][-A-Za-z0-9_.]*)?[A-Za-z0-9])?$")


def is_label(name: str) -> bool:
    return len(name) <= 63 and bool(DNS1123_LABEL.match(name))


def is_subdomain(name: str) -> bool:
    return len(name) <= 253 and bool(DNS1123_SUBDOMAIN.match(name))


def validate_name(name: str, field: str = "name", *, subdomain: bool = False) -> str:
    ok = is_subdomain(name) if subdomain else is_label(name)
    if not ok:
        raise ValidationFailed(
            f"'{name}' is not a valid Kubernetes name: use lowercase letters, digits and '-', "
            f"start and end with a letter or digit, max {253 if subdomain else 63} characters",
            params={"field": field, "rule": "dns1123"},
        )
    return name
