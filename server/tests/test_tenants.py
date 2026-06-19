"""Tests for tenant management (SuperAdmin only) + tenant isolation."""


class TestTenantCRUD:
    def test_create_tenant_superadmin(self, client, auth_headers):
        resp = client.post(
            "/api/v1/tenants",
            json={"name": "Acme Corp", "plan": "pro", "max_probes": 10},
            headers=auth_headers,
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["name"] == "Acme Corp"
        assert data["slug"] == "acme-corp"

    def test_create_tenant_duplicate(self, client, auth_headers):
        client.post("/api/v1/tenants", json={"name": "Dup Co"}, headers=auth_headers)
        resp = client.post("/api/v1/tenants", json={"name": "Dup Co"}, headers=auth_headers)
        assert resp.status_code == 409

    def test_create_tenant_missing_name(self, client, auth_headers):
        resp = client.post("/api/v1/tenants", json={}, headers=auth_headers)
        assert resp.status_code == 400

    def test_list_tenants_superadmin(self, client, auth_headers, tenant):
        resp = client.get("/api/v1/tenants", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, list)
        assert len(data) >= 1

    def test_get_tenant(self, client, auth_headers, tenant):
        resp = client.get(f"/api/v1/tenants/{tenant['id']}", headers=auth_headers)
        assert resp.status_code == 200

    def test_get_tenant_not_found(self, client, auth_headers):
        resp = client.get("/api/v1/tenants/nonexistent-id", headers=auth_headers)
        assert resp.status_code == 404

    def test_update_tenant(self, client, auth_headers, tenant):
        resp = client.patch(
            f"/api/v1/tenants/{tenant['id']}",
            json={"plan": "enterprise"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.get_json()["plan"] == "enterprise"

    def test_deactivate_tenant(self, client, auth_headers):
        resp = client.post(
            "/api/v1/tenants",
            json={"name": "To Delete Corp"},
            headers=auth_headers,
        )
        tid = resp.get_json()["id"]
        resp2 = client.delete(f"/api/v1/tenants/{tid}", headers=auth_headers)
        assert resp2.status_code == 200


class TestTenantIsolation:
    def test_tenant_admin_cannot_access_tenants_endpoint(self, client, tenant_auth_headers):
        resp = client.get("/api/v1/tenants", headers=tenant_auth_headers)
        assert resp.status_code == 403

    def test_tenant_admin_cannot_create_tenant(self, client, tenant_auth_headers):
        resp = client.post(
            "/api/v1/tenants",
            json={"name": "Evil Corp"},
            headers=tenant_auth_headers,
        )
        assert resp.status_code == 403
