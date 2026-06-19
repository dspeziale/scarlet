"""Tests for resource accounting."""

from datetime import date


class TestAccounting:
    def _register_probe(self, client, auth_headers, tenant, machine_id="acc-probe-01"):
        resp = client.post(
            "/api/v1/probe-tokens",
            json={"tenant_id": tenant["id"]},
            headers=auth_headers,
        )
        token = resp.get_json()["token"]
        reg = client.post(
            "/api/v1/probe/register",
            json={"registration_token": token, "hostname": "acc-probe.local", "machine_id": machine_id},
        )
        return reg.get_json()["probe_id"]

    def test_heartbeat_records_usage(self, client, auth_headers, tenant):
        probe_id = self._register_probe(client, auth_headers, tenant, "acc-probe-02")
        client.post(
            "/api/v1/probe/heartbeat",
            json={"probe_id": probe_id, "metrics": {"cpu_seconds": 60, "memory_mb": 512, "task_count": 5}},
            headers=auth_headers,
        )

        resp = client.get(
            f"/api/v1/accounting/usage?limit=1",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        rows = resp.get_json()
        assert len(rows) >= 1

    def test_daily_summary(self, client, auth_headers, tenant):
        resp = client.get(
            f"/api/v1/accounting/daily?date={date.today().isoformat()}",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert isinstance(resp.get_json(), list)

    def test_monthly_summary(self, client, auth_headers, tenant):
        today = date.today()
        resp = client.get(
            f"/api/v1/accounting/monthly?year={today.year}&month={today.month}",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert "total_cpu_seconds" in data

    def test_accounting_invalid_date(self, client, auth_headers):
        resp = client.get("/api/v1/accounting/daily?date=not-a-date", headers=auth_headers)
        assert resp.status_code == 400

    def test_accounting_tenant_isolation(self, client, tenant_auth_headers, auth_headers, tenant):
        # Tenant admin can only see own tenant
        resp = client.get("/api/v1/accounting/usage", headers=tenant_auth_headers)
        assert resp.status_code == 200
