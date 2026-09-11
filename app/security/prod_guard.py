"""Production safety controls.

``ProductionGuard`` centralizes every rule that makes PROD operations harder to
perform by accident: typed confirmation phrase, mandatory reason, optional
second-person approval, rollback allowance and the stricter ``prod.*``
permission requirement.
"""

from __future__ import annotations

from dataclasses import dataclass

from flask import current_app

from app.errors import ApprovalRequiredError, ProductionSafetyError, ValidationError
from app.security.rbac import check_permission

DESTRUCTIVE_OPERATIONS = {"STOP", "DEPLOY", "ROLLBACK", "RESTART", "DELETE", "SCALE"}


@dataclass(frozen=True)
class ProdRequirements:
    is_production: bool
    require_confirmation: bool
    confirmation_phrase: str
    require_reason: bool
    require_approval: bool
    allow_rollback: bool

    def to_dict(self) -> dict:
        return {
            "is_production": self.is_production,
            "require_confirmation": self.require_confirmation,
            "confirmation_phrase": self.confirmation_phrase if self.require_confirmation else None,
            "require_reason": self.require_reason,
            "require_approval": self.require_approval,
            "allow_rollback": self.allow_rollback,
        }


class ProductionGuard:
    def __init__(self, settings=None) -> None:
        # settings: SettingsService-like object with get(key, default)
        self._settings = settings

    def _setting(self, key: str, default):
        if self._settings is not None:
            try:
                return self._settings.get(key, default)
            except Exception:  # noqa: BLE001 - settings service must never break safety checks
                return default
        return current_app.config.get(key, default)

    def requirements(self, environment) -> ProdRequirements:
        is_prod = bool(environment and environment.is_production)
        if not is_prod:
            return ProdRequirements(False, False, "", False, False, True)
        return ProdRequirements(
            is_production=True,
            require_confirmation=bool(
                self._setting("SCARLET_PROD_REQUIRE_CONFIRMATION", True)
                or environment.require_confirmation
            ),
            confirmation_phrase=str(
                self._setting("SCARLET_PROD_CONFIRMATION_PHRASE", "DEPLOY TO PROD")
            ),
            require_reason=bool(self._setting("SCARLET_PROD_REQUIRE_REASON", True)),
            require_approval=bool(
                self._setting("SCARLET_PROD_REQUIRE_APPROVAL", False)
                or environment.require_approval
            ),
            allow_rollback=bool(
                self._setting("SCARLET_PROD_ALLOW_ROLLBACK", True) and environment.allow_rollback
            ),
        )

    def authorize(self, permission: str, environment, *, user=None) -> None:
        """Permission check that automatically requires the prod.* variant on PROD."""
        check_permission(
            permission, production=bool(environment and environment.is_production), user=user
        )

    def check_operation(
        self,
        *,
        environment,
        operation: str,
        confirmation: str | None,
        reason: str | None,
        phrase_override: str | None = None,
    ) -> ProdRequirements:
        """Validate the confirmation/reason supplied for a (potentially) PROD operation."""
        reqs = self.requirements(environment)
        if not reqs.is_production:
            return reqs
        operation = operation.upper()
        if operation == "ROLLBACK" and not reqs.allow_rollback:
            raise ProductionSafetyError("Rollback is disabled for production environments.")
        if operation in DESTRUCTIVE_OPERATIONS:
            if reqs.require_reason and not (reason or "").strip():
                raise ValidationError(
                    "A reason is required for production operations.",
                    errors={"reason": ["Required for PROD operations."]},
                )
            if reqs.require_confirmation:
                expected = phrase_override or self.expected_phrase(
                    operation, reqs.confirmation_phrase
                )
                if (confirmation or "").strip() != expected:
                    raise ProductionSafetyError(
                        f"Production confirmation failed. Type exactly: {expected}",
                        details={"expected": expected},
                    )
        return reqs

    @staticmethod
    def expected_phrase(operation: str, deploy_phrase: str) -> str:
        operation = operation.upper()
        if operation == "DEPLOY":
            return deploy_phrase
        return f"{operation} PROD"

    def check_approval(self, deployment, *, approver=None) -> None:
        """Verify that a PROD deployment requiring approval has been approved."""
        reqs = self.requirements(deployment.environment)
        if not reqs.require_approval:
            return
        approved = [a for a in deployment.approvals if a.status == "APPROVED"]
        if not approved:
            raise ApprovalRequiredError()
        if approver is not None and any(
            a.decided_by_id == deployment.requested_by_id for a in approved
        ):
            raise ProductionSafetyError(
                "A deployment cannot be approved by the user who requested it."
            )
