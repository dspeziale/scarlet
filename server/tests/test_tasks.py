"""Tests for task lifecycle."""


class TestTasks:
    def test_create_task(self, client, auth_headers, tenant):
        resp = client.post(
            "/api/v1/tasks",
            json={"task_type": "network_discovery", "name": "Test Scan", "parameters": {"cidr": "192.168.1.0/24"}},
            headers=auth_headers,
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["task_type"] == "network_discovery"
        assert data["status"] == "queued"

    def test_create_task_invalid_type(self, client, auth_headers):
        resp = client.post(
            "/api/v1/tasks",
            json={"task_type": "invalid_type"},
            headers=auth_headers,
        )
        assert resp.status_code == 400

    def test_list_tasks(self, client, auth_headers, tenant):
        client.post("/api/v1/tasks", json={"task_type": "wifi_scan"}, headers=auth_headers)
        resp = client.get("/api/v1/tasks", headers=auth_headers)
        assert resp.status_code == 200
        assert isinstance(resp.get_json(), list)

    def test_cancel_task(self, client, auth_headers, tenant):
        resp = client.post("/api/v1/tasks", json={"task_type": "ble_scan"}, headers=auth_headers)
        task_id = resp.get_json()["id"]
        cancel = client.delete(f"/api/v1/tasks/{task_id}", headers=auth_headers)
        assert cancel.status_code == 200

    def test_assign_task_to_probe(self, client, auth_headers, tenant):
        # Register a probe
        token_resp = client.post("/api/v1/probe-tokens", json={"tenant_id": tenant["id"]}, headers=auth_headers)
        token = token_resp.get_json()["token"]
        probe_resp = client.post(
            "/api/v1/probe/register",
            json={"registration_token": token, "hostname": "task-probe.local", "machine_id": "task-probe-001"},
        )
        probe_id = probe_resp.get_json()["probe_id"]

        task_resp = client.post("/api/v1/tasks", json={"task_type": "os_fingerprinting"}, headers=auth_headers)
        task_id = task_resp.get_json()["id"]

        assign_resp = client.post(
            f"/api/v1/tasks/{task_id}/assign",
            json={"probe_id": probe_id},
            headers=auth_headers,
        )
        assert assign_resp.status_code == 200
        assert assign_resp.get_json()["status"] == "assigned"

    def test_get_task_not_found(self, client, auth_headers):
        resp = client.get("/api/v1/tasks/nonexistent", headers=auth_headers)
        assert resp.status_code == 404
