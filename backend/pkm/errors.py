"""Application errors with stable codes.

The API never returns a bare "500 Internal Server Error": every error has a
machine-readable `code` that the UI translates into an explanation, a probable
cause and suggested actions, plus optional technical `details`.
"""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    status_code = 500
    code = "internal_error"

    def __init__(self, message: str = "", *, details: str | None = None, params: dict[str, Any] | None = None):
        super().__init__(message or self.code)
        self.message = message or self.code
        self.details = details
        self.params = params or {}


class BadRequest(AppError):
    status_code = 400
    code = "bad_request"


class ValidationFailed(AppError):
    status_code = 422
    code = "validation_failed"


class Unauthorized(AppError):
    status_code = 401
    code = "unauthorized"


class Forbidden(AppError):
    status_code = 403
    code = "forbidden"


class NotFound(AppError):
    status_code = 404
    code = "not_found"


class Conflict(AppError):
    status_code = 409
    code = "conflict"


class ConfirmationRequired(AppError):
    status_code = 428
    code = "confirmation_required"


class RateLimited(AppError):
    status_code = 429
    code = "rate_limited"


class ServiceUnavailable(AppError):
    status_code = 503
    code = "service_unavailable"


class NotSupported(AppError):
    status_code = 501
    code = "not_supported"


# --- Kubernetes ---------------------------------------------------------------
class K8sNotConfigured(ServiceUnavailable):
    code = "k8s_not_configured"


class K8sUnavailable(ServiceUnavailable):
    code = "k8s_unavailable"


class K8sTimeout(ServiceUnavailable):
    status_code = 504
    code = "k8s_timeout"


class K8sAuthFailed(ServiceUnavailable):
    status_code = 502
    code = "k8s_auth_failed"


class K8sForbidden(Forbidden):
    code = "k8s_forbidden"


class K8sNotFound(NotFound):
    code = "k8s_not_found"


class K8sConflict(Conflict):
    code = "k8s_conflict"


class K8sInvalid(ValidationFailed):
    code = "k8s_invalid"


class K8sUnsupported(NotSupported):
    code = "k8s_unsupported"


# --- Podman -------------------------------------------------------------------
class PodmanNotConfigured(ServiceUnavailable):
    code = "podman_not_configured"


class PodmanUnavailable(ServiceUnavailable):
    code = "podman_unavailable"


class PodmanTimeout(ServiceUnavailable):
    status_code = 504
    code = "podman_timeout"


class PodmanNotFound(NotFound):
    code = "podman_not_found"


class PodmanError(AppError):
    status_code = 502
    code = "podman_error"


class MetricsUnavailable(ServiceUnavailable):
    code = "metrics_unavailable"
