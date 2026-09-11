"""Strict input validators used by services and command builders.

Everything that ends up inside a remote command line MUST pass through one of
these validators first (application code, version, path segment, image name...).
The regular expressions are deliberately conservative allowlists.
"""

from __future__ import annotations

import ipaddress
import re
from typing import Any

from app.errors import ValidationError

HOSTNAME_RE = re.compile(
    r"^(?=.{1,253}$)(?!-)[A-Za-z0-9-]{1,63}(?<!-)(\.(?!-)[A-Za-z0-9-]{1,63}(?<!-))*\.?$"
)
APP_CODE_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
VERSION_RE = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-((?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?"
    r"(?:\+([0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?$"
)
IMAGE_NAME_RE = re.compile(
    r"^(?:[a-z0-9]+(?:[._-][a-z0-9]+)*(?::[0-9]{2,5})?/)?"
    r"[a-z0-9]+(?:[._-][a-z0-9]+)*(?:/[a-z0-9]+(?:[._-][a-z0-9]+)*)*$"
)
IMAGE_TAG_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$")
PATH_SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
ENV_KEY_RE = re.compile(r"^[A-Z_][A-Z0-9_]{0,127}$")
USERNAME_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
K8S_NAME_RE = re.compile(r"^[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?$")
CONTAINER_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}$")
URL_PATH_RE = re.compile(r"^/[A-Za-z0-9._~\-/%?=&+]*$")
LOG_SEARCH_RE = re.compile(r"^[\w .:\-\[\]/=,'\"()]{0,200}$")


def validate_hostname(value: str) -> str:
    value = (value or "").strip()
    if not value or len(value) > 253 or not HOSTNAME_RE.match(value):
        raise ValidationError(
            "Invalid hostname.", errors={"hostname": ["Invalid hostname format."]}
        )
    if value.lower() in {"localhost", "localhost.localdomain"}:
        raise ValidationError(
            "Target hostname cannot be localhost.", errors={"hostname": ["Not allowed."]}
        )
    return value.rstrip(".")


def validate_ip_address(value: str | None, *, allow_empty: bool = True) -> str | None:
    if value is None or value.strip() == "":
        if allow_empty:
            return None
        raise ValidationError("IP address is required.", errors={"ip_address": ["Required."]})
    try:
        addr = ipaddress.ip_address(value.strip())
    except ValueError as exc:
        raise ValidationError(
            "Invalid IP address.", errors={"ip_address": ["Must be a valid IPv4 or IPv6 address."]}
        ) from exc
    if addr.is_loopback or addr.is_multicast or addr.is_unspecified or addr.is_reserved:
        raise ValidationError(
            "IP address not allowed.",
            errors={"ip_address": ["Loopback/multicast/reserved addresses are not allowed."]},
        )
    return str(addr)


def validate_port(value: Any, *, field: str = "port") -> int:
    try:
        port = int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError("Invalid port.", errors={field: ["Must be an integer."]}) from exc
    if not 1 <= port <= 65535:
        raise ValidationError("Invalid port.", errors={field: ["Must be between 1 and 65535."]})
    return port


def validate_app_code(value: str) -> str:
    value = (value or "").strip().lower()
    if not value or len(value) > 64 or not APP_CODE_RE.match(value):
        raise ValidationError(
            "Invalid application code.",
            errors={
                "code": ["Use lowercase letters, digits and single dashes (e.g. customer-api)."]
            },
        )
    return value


def parse_semver(value: str) -> dict[str, Any]:
    value = (value or "").strip()
    match = VERSION_RE.match(value)
    if not match or len(value) > 64:
        raise ValidationError(
            "Invalid version.",
            errors={
                "version": ["Must follow semantic versioning, e.g. 2.5.0 or 2.5.0-rc.1+build.7"]
            },
        )
    return {
        "version": value,
        "major": int(match.group(1)),
        "minor": int(match.group(2)),
        "patch": int(match.group(3)),
        "prerelease": match.group(4),
        "build_metadata": match.group(5),
    }


def validate_version(value: str) -> str:
    return parse_semver(value)["version"]


def validate_image_name(value: str) -> str:
    value = (value or "").strip()
    if not value or len(value) > 255 or not IMAGE_NAME_RE.match(value):
        raise ValidationError(
            "Invalid image name.", errors={"image.name": ["Invalid container image reference."]}
        )
    return value


def validate_image_tag(value: str) -> str:
    value = (value or "").strip()
    if not value or not IMAGE_TAG_RE.match(value):
        raise ValidationError("Invalid image tag.", errors={"image.tag": ["Invalid tag format."]})
    return value


def validate_path_segment(value: str, *, field: str = "path") -> str:
    """A single filename / directory component: no slashes, no dot-dot."""
    value = (value or "").strip()
    if not value or value in {".", ".."} or not PATH_SEGMENT_RE.match(value):
        raise ValidationError("Invalid path segment.", errors={field: ["Invalid characters."]})
    return value


def validate_relative_path(value: str, *, field: str = "path", max_depth: int = 16) -> str:
    """Relative path inside a package (used for hooks/config files)."""
    value = (value or "").strip().replace("\\", "/")
    if not value or value.startswith("/") or "\x00" in value:
        raise ValidationError("Invalid relative path.", errors={field: ["Must be relative."]})
    parts = value.split("/")
    if len(parts) > max_depth:
        raise ValidationError("Path too deep.", errors={field: ["Too many components."]})
    for part in parts:
        validate_path_segment(part, field=field)
    return "/".join(parts)


def validate_env_key(value: str) -> str:
    value = (value or "").strip()
    if not ENV_KEY_RE.match(value):
        raise ValidationError(
            "Invalid environment variable name.",
            errors={"key": ["Use uppercase letters, digits and underscores."]},
        )
    return value


def validate_ssh_username(value: str) -> str:
    value = (value or "").strip()
    if not USERNAME_RE.match(value):
        raise ValidationError(
            "Invalid SSH username.", errors={"ssh_username": ["Invalid Linux username."]}
        )
    return value


def validate_k8s_name(value: str, *, field: str = "name") -> str:
    value = (value or "").strip()
    if not value or len(value) > 63 or not K8S_NAME_RE.match(value):
        raise ValidationError(
            "Invalid Kubernetes name.", errors={field: ["Must be a DNS-1123 label."]}
        )
    return value


def validate_container_name(value: str) -> str:
    value = (value or "").strip()
    if not CONTAINER_NAME_RE.match(value):
        raise ValidationError("Invalid container name.", errors={"name": ["Invalid characters."]})
    return value


def validate_url_path(value: str) -> str:
    value = (value or "").strip()
    if not value or len(value) > 512 or not URL_PATH_RE.match(value) or ".." in value:
        raise ValidationError(
            "Invalid URL path.", errors={"path": ["Must start with / and contain safe characters."]}
        )
    return value


def validate_log_search(value: str | None) -> str:
    value = (value or "").strip()
    if len(value) > 200 or not LOG_SEARCH_RE.match(value):
        raise ValidationError(
            "Invalid search expression.", errors={"search": ["Invalid characters."]}
        )
    return value


def validate_int_range(
    value: Any, *, field: str, minimum: int, maximum: int, default: int | None = None
) -> int:
    if value is None or value == "":
        if default is not None:
            return default
        raise ValidationError(f"{field} is required.", errors={field: ["Required."]})
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(
            f"{field} must be an integer.", errors={field: ["Must be an integer."]}
        ) from exc
    if number < minimum or number > maximum:
        raise ValidationError(
            f"{field} out of range.", errors={field: [f"Must be between {minimum} and {maximum}."]}
        )
    return number


def validate_enum(value: Any, enum_cls, *, field: str):
    parsed = enum_cls.parse(value)
    if parsed is None:
        raise ValidationError(
            f"Invalid {field}.", errors={field: [f"Must be one of: {', '.join(enum_cls.values())}"]}
        )
    return parsed
