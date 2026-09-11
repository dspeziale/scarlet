import pytest

from app.errors import AuthorizationError, ProductionSafetyError, ValidationError
from app.security.prod_guard import ProductionGuard
from app.security.rbac import (
    DEFAULT_ROLES,
    PERMISSIONS,
    PROD_SENSITIVE,
    check_permission,
    user_has_permission,
)


class FakeUser:
    def __init__(self, codes, active=True):
        self.permission_codes = set(codes)
        self.is_active = active


def test_every_role_permission_exists_in_catalogue():
    for spec in DEFAULT_ROLES.values():
        assert spec["permissions"] <= set(PERMISSIONS)


def test_prod_sensitive_permissions_have_prod_variant():
    for perm in PROD_SENSITIVE:
        assert f"prod.{perm}" in PERMISSIONS


def test_operator_cannot_deploy_to_prod_but_can_to_dev():
    operator = FakeUser(DEFAULT_ROLES["OPERATOR"]["permissions"])
    assert user_has_permission(operator, "deployment.execute")
    assert not user_has_permission(operator, "deployment.execute", production=True)
    prod_operator = FakeUser(DEFAULT_ROLES["PROD_OPERATOR"]["permissions"])
    assert user_has_permission(prod_operator, "deployment.execute", production=True)


def test_viewer_is_read_only():
    viewer = FakeUser(DEFAULT_ROLES["VIEWER"]["permissions"])
    assert user_has_permission(viewer, "host.view")
    for perm in (
        "host.create",
        "deployment.execute",
        "lifecycle.stop",
        "user.manage",
        "audit.view",
    ):
        assert not user_has_permission(viewer, perm)


def test_auditor_sees_audit_only_extra():
    auditor = FakeUser(DEFAULT_ROLES["AUDITOR"]["permissions"])
    assert user_has_permission(auditor, "audit.view")
    assert user_has_permission(auditor, "audit.export")
    assert not user_has_permission(auditor, "deployment.execute")


def test_inactive_user_has_nothing():
    assert not user_has_permission(FakeUser(set(PERMISSIONS), active=False), "host.view")


def test_check_permission_raises(app):
    with app.test_request_context():
        with pytest.raises(AuthorizationError):
            check_permission("deployment.execute", user=FakeUser({"host.view"}))
        with pytest.raises(AuthorizationError):
            check_permission(
                "deployment.execute", production=True, user=FakeUser({"deployment.execute"})
            )
        check_permission(
            "deployment.execute",
            production=True,
            user=FakeUser({"deployment.execute", "prod.deployment.execute"}),
        )


class Env:
    def __init__(self, prod, confirmation=True, approval=False, rollback=True):
        self.is_production = prod
        self.require_confirmation = confirmation
        self.require_approval = approval
        self.allow_rollback = rollback


class Settings:
    def __init__(self, **values):
        self.values = values

    def get(self, key, default=None):
        return self.values.get(key, default)


def test_prod_guard_requires_phrase_and_reason():
    guard = ProductionGuard(
        Settings(
            SCARLET_PROD_REQUIRE_CONFIRMATION=True,
            SCARLET_PROD_REQUIRE_REASON=True,
            SCARLET_PROD_CONFIRMATION_PHRASE="DEPLOY TO PROD",
        )
    )
    with pytest.raises(ValidationError):
        guard.check_operation(
            environment=Env(True), operation="DEPLOY", confirmation="DEPLOY TO PROD", reason=""
        )
    with pytest.raises(ProductionSafetyError):
        guard.check_operation(
            environment=Env(True),
            operation="DEPLOY",
            confirmation="deploy to prod",
            reason="ticket 1",
        )
    reqs = guard.check_operation(
        environment=Env(True), operation="DEPLOY", confirmation="DEPLOY TO PROD", reason="ticket 1"
    )
    assert reqs.is_production
    # STOP uses "STOP PROD"
    with pytest.raises(ProductionSafetyError):
        guard.check_operation(
            environment=Env(True), operation="STOP", confirmation="DEPLOY TO PROD", reason="x"
        )
    guard.check_operation(
        environment=Env(True), operation="STOP", confirmation="STOP PROD", reason="x"
    )


def test_prod_guard_dev_needs_nothing():
    guard = ProductionGuard(Settings())
    reqs = guard.check_operation(
        environment=Env(False), operation="DEPLOY", confirmation=None, reason=None
    )
    assert not reqs.is_production


def test_prod_guard_rollback_disabled():
    guard = ProductionGuard(Settings(SCARLET_PROD_ALLOW_ROLLBACK=False))
    with pytest.raises(ProductionSafetyError):
        guard.check_operation(
            environment=Env(True), operation="ROLLBACK", confirmation="ROLLBACK PROD", reason="x"
        )


def test_prod_guard_read_only_ops_do_not_need_confirmation():
    guard = ProductionGuard(Settings(SCARLET_PROD_REQUIRE_CONFIRMATION=True))
    guard.check_operation(environment=Env(True), operation="STATUS", confirmation=None, reason=None)
