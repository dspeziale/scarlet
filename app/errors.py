"""Typed exceptions used across SCARLET.

Every exception carries a stable ``code`` (machine readable), an ``http_status``
and a user-friendly ``message``. Technical details that must never reach the UI
go in ``details`` and are only written to server logs.
"""

from __future__ import annotations

from typing import Any


class ScarletError(Exception):
    """Base class for all application errors."""

    code = "SCARLET_ERROR"
    http_status = 500
    user_message = "An unexpected error occurred."
    retryable = False

    def __init__(
        self,
        message: str | None = None,
        *,
        details: dict[str, Any] | None = None,
        retryable: bool | None = None,
    ) -> None:
        self.message = message or self.user_message
        self.details = details or {}
        if retryable is not None:
            self.retryable = retryable
        super().__init__(self.message)

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message}


# --- validation / input -------------------------------------------------------


class ValidationError(ScarletError):
    code = "VALIDATION_ERROR"
    http_status = 400
    user_message = "Invalid input."

    def __init__(
        self, message: str | None = None, *, errors: dict[str, Any] | None = None, **kw: Any
    ) -> None:
        super().__init__(message, **kw)
        self.errors = errors or {}

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        if self.errors:
            data["errors"] = self.errors
        return data


class NotFoundError(ScarletError):
    code = "NOT_FOUND"
    http_status = 404
    user_message = "The requested resource was not found."


class ConflictError(ScarletError):
    code = "CONFLICT"
    http_status = 409
    user_message = "The operation conflicts with the current state."


# --- security -----------------------------------------------------------------


class AuthenticationError(ScarletError):
    code = "AUTHENTICATION_REQUIRED"
    http_status = 401
    user_message = "Authentication required."


class AuthorizationError(ScarletError):
    code = "FORBIDDEN"
    http_status = 403
    user_message = "You are not allowed to perform this action."


class ProductionSafetyError(AuthorizationError):
    code = "PRODUCTION_SAFETY"
    http_status = 403
    user_message = "Production safety controls blocked this operation."


class ApprovalRequiredError(ProductionSafetyError):
    code = "APPROVAL_REQUIRED"
    user_message = "This production deployment requires approval by another authorized user."


class RateLimitError(ScarletError):
    code = "RATE_LIMITED"
    http_status = 429
    user_message = "Too many requests. Please try again later."


class SecurityError(ScarletError):
    code = "SECURITY_ERROR"
    http_status = 400
    user_message = "The request was rejected by a security control."


class UnsafeCommandError(SecurityError):
    code = "UNSAFE_COMMAND"
    user_message = "The requested command is not allowed."


class ConfigurationError(ScarletError):
    code = "CONFIGURATION_ERROR"
    http_status = 500
    user_message = "The server configuration is invalid."


# --- SSH ----------------------------------------------------------------------


class SSHError(ScarletError):
    code = "SSH_ERROR"
    http_status = 502
    user_message = "SSH communication with the target host failed."


class SSHConnectionError(SSHError):
    code = "SSH_CONNECTION_ERROR"
    user_message = "Unable to connect to the target host over SSH."
    retryable = True


class SSHAuthenticationError(SSHError):
    code = "SSH_AUTHENTICATION_ERROR"
    user_message = "SSH authentication to the target host failed."


class SSHHostKeyError(SSHError):
    code = "SSH_HOST_KEY_ERROR"
    user_message = (
        "The SSH host key of the target is unknown or has changed. "
        "An administrator must review and approve the host fingerprint."
    )


class SSHTimeoutError(SSHError):
    code = "SSH_TIMEOUT"
    user_message = "The SSH operation timed out."
    retryable = True


class RemoteCommandError(SSHError):
    code = "REMOTE_COMMAND_ERROR"
    user_message = "A remote command failed on the target host."

    def __init__(
        self,
        message: str | None = None,
        *,
        exit_code: int | None = None,
        stdout: str = "",
        stderr: str = "",
        **kw: Any,
    ) -> None:
        super().__init__(message, **kw)
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr


class FileTransferError(SSHError):
    code = "FILE_TRANSFER_ERROR"
    user_message = "File transfer to the target host failed."
    retryable = True


# --- packages / manifests -----------------------------------------------------


class PackageValidationError(ValidationError):
    code = "PACKAGE_VALIDATION_ERROR"
    user_message = "The release package is invalid."


class ManifestValidationError(PackageValidationError):
    code = "MANIFEST_VALIDATION_ERROR"
    user_message = "The package manifest is invalid."


class DuplicateReleaseError(ConflictError):
    code = "DUPLICATE_RELEASE"
    user_message = "This application version has already been released."


class ArtifactStorageError(ScarletError):
    code = "ARTIFACT_STORAGE_ERROR"
    user_message = "The artifact storage operation failed."


# --- runtime / deployment / lifecycle -----------------------------------------


class RuntimeNotSupportedError(ScarletError):
    code = "RUNTIME_NOT_SUPPORTED"
    http_status = 400
    user_message = "The requested runtime is not supported for this target."


class RuntimeOperationError(ScarletError):
    code = "RUNTIME_ERROR"
    http_status = 502
    user_message = "The container runtime reported an error."


class DeploymentError(ScarletError):
    code = "DEPLOYMENT_ERROR"
    http_status = 500
    user_message = "The deployment failed."


class PreflightError(DeploymentError):
    code = "PREFLIGHT_FAILED"
    http_status = 409
    user_message = "Pre-flight checks failed."


class InvalidStateTransitionError(DeploymentError):
    code = "INVALID_STATE_TRANSITION"
    http_status = 409
    user_message = "The requested state transition is not allowed."


class HealthCheckError(ScarletError):
    code = "HEALTH_CHECK_FAILED"
    http_status = 502
    user_message = "The application health check failed."


class LifecycleError(ScarletError):
    code = "LIFECYCLE_ERROR"
    http_status = 500
    user_message = "The lifecycle operation failed."


class ConcurrencyError(ConflictError):
    code = "CONCURRENT_OPERATION"
    user_message = "Another operation is already running on this application/target."


class OperationTimeoutError(ScarletError):
    code = "OPERATION_TIMEOUT"
    http_status = 504
    user_message = "The operation timed out."
    retryable = True
