"""Tests for RBAC enforcement."""


class TestRBAC:
    def test_superadmin_can_list_tenants(self, client, auth_headers):
        resp = client.get("/api/v1/tenants", headers=auth_headers)
        assert resp.status_code == 200

    def test_tenant_admin_cannot_list_tenants(self, client, tenant_auth_headers):
        resp = client.get("/api/v1/tenants", headers=tenant_auth_headers)
        assert resp.status_code == 403

    def test_unauthenticated_blocked(self, client):
        resp = client.get("/api/v1/probes")
        assert resp.status_code == 401

    def test_readonly_user_cannot_create_task(self, client, auth_headers, tenant):
        # Create a ReadOnly user
        resp = client.post(
            "/api/v1/users",
            json={
                "email": "readonly@test.local",
                "username": "readonly1",
                "password": "Readonly123!",
                "tenant_id": tenant["id"],
                "roles": ["ReadOnly"],
            },
            headers=auth_headers,
        )
        assert resp.status_code == 201

        login = client.post(
            "/api/v1/auth/login",
            json={"email": "readonly@test.local", "password": "Readonly123!"},
        )
        ro_token = login.get_json()["access_token"]
        ro_headers = {"Authorization": f"Bearer {ro_token}"}

        # ReadOnly role: cannot create tasks
        task_resp = client.post(
            "/api/v1/tasks",
            json={"task_type": "network_discovery"},
            headers=ro_headers,
        )
        assert task_resp.status_code == 403

    def test_operator_can_create_task(self, client, auth_headers, tenant):
        # Create an Operator user
        client.post(
            "/api/v1/users",
            json={
                "email": "operator@test.local",
                "username": "operator1",
                "password": "Operator123!",
                "tenant_id": tenant["id"],
                "roles": ["Operator"],
            },
            headers=auth_headers,
        )
        login = client.post(
            "/api/v1/auth/login",
            json={"email": "operator@test.local", "password": "Operator123!"},
        )
        op_headers = {"Authorization": f"Bearer {login.get_json()['access_token']}"}

        resp = client.post(
            "/api/v1/tasks",
            json={"task_type": "network_discovery", "name": "test-scan"},
            headers=op_headers,
        )
        assert resp.status_code == 201

    def test_global_audit_requires_superadmin(self, client, tenant_auth_headers):
        resp = client.get("/api/v1/audit/user/someuser", headers=tenant_auth_headers)
        assert resp.status_code == 403
