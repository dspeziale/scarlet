"""Tests for audit log immutability and query endpoints."""


class TestAuditLog:
    def test_login_creates_audit_entry(self, client, db, auth_headers):
        resp = client.get("/api/v1/audit", headers=auth_headers)
        assert resp.status_code == 200
        logs = resp.get_json()
        actions = [l["action"] for l in logs]
        assert "user.login" in actions

    def test_audit_is_tenant_scoped(self, client, tenant_auth_headers, auth_headers):
        tenant_logs = client.get("/api/v1/audit", headers=tenant_auth_headers)
        assert tenant_logs.status_code == 200

        global_logs = client.get("/api/v1/audit", headers=auth_headers)
        assert global_logs.status_code == 200
        # SuperAdmin sees more records
        assert len(global_logs.get_json()) >= len(tenant_logs.get_json())

    def test_audit_immutability(self, app, db):
        """Verify that updating an AuditLog raises RuntimeError."""
        from app.models.audit import AuditLog
        from app.extensions import db as _db
        import pytest

        with app.app_context():
            log = AuditLog(action="test.immutable", tenant_id=None, user_id=None)
            _db.session.add(log)
            _db.session.flush()

            with pytest.raises(RuntimeError, match="immutable"):
                from sqlalchemy import event
                # Directly trigger the before_update event
                from sqlalchemy.orm import attributes
                log.action = "mutated"
                from app.models.audit import _block_audit_update
                _block_audit_update(None, None, log)

    def test_superadmin_can_see_audit_by_user(self, client, auth_headers):
        resp = client.get("/api/v1/audit/user/some-user-id", headers=auth_headers)
        # Returns empty list (user doesn't exist), not 403
        assert resp.status_code == 200
