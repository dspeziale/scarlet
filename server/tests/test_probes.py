"""Tests for probe registration flow and cryptographic provisioning."""


class TestProbeRegistration:
    def _get_token(self, client, auth_headers, tenant):
        resp = client.post(
            "/api/v1/probe-tokens",
            json={"tenant_id": tenant["id"], "label": "test-token"},
            headers=auth_headers,
        )
        assert resp.status_code == 201
        return resp.get_json()["token"]

    def test_generate_registration_token(self, client, auth_headers, tenant):
        resp = client.post(
            "/api/v1/probe-tokens",
            json={"tenant_id": tenant["id"]},
            headers=auth_headers,
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["token"].startswith("PRB-")
        assert len(data["token"]) == 16  # PRB- + 12 chars

    def test_register_probe_valid_token(self, client, auth_headers, tenant):
        token = self._get_token(client, auth_headers, tenant)
        resp = client.post(
            "/api/v1/probe/register",
            json={
                "registration_token": token,
                "hostname": "probe-01.local",
                "machine_id": "aabbccdd1234",
                "platform": "linux",
                "architecture": "x86_64",
                "agent_version": "1.0.0",
            },
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert "probe_id" in data
        assert data["status"] == "pending_keys"

    def test_register_probe_invalid_token(self, client):
        resp = client.post(
            "/api/v1/probe/register",
            json={
                "registration_token": "PRB-INVALIDTOKEN",
                "hostname": "probe.local",
                "machine_id": "deadbeef",
            },
        )
        assert resp.status_code == 400

    def test_register_probe_reuse_token(self, client, auth_headers, tenant):
        token = self._get_token(client, auth_headers, tenant)
        payload = {
            "registration_token": token,
            "hostname": "probe-reuse.local",
            "machine_id": "uniqueid001",
        }
        resp1 = client.post("/api/v1/probe/register", json=payload)
        assert resp1.status_code == 201

        payload["machine_id"] = "uniqueid002"
        resp2 = client.post("/api/v1/probe/register", json=payload)
        assert resp2.status_code == 400  # token already used

    def test_register_probe_missing_fields(self, client, auth_headers, tenant):
        token = self._get_token(client, auth_headers, tenant)
        resp = client.post(
            "/api/v1/probe/register",
            json={"registration_token": token},
        )
        assert resp.status_code == 400


class TestProbeKeyProvisioning:
    def _register(self, client, auth_headers, tenant, machine_id="crypto-test-01"):
        resp = client.post(
            "/api/v1/probe-tokens",
            json={"tenant_id": tenant["id"]},
            headers=auth_headers,
        )
        token = resp.get_json()["token"]
        resp2 = client.post(
            "/api/v1/probe/register",
            json={"registration_token": token, "hostname": "crypto-probe.local", "machine_id": machine_id},
        )
        return resp2.get_json()["probe_id"]

    def test_provision_keys(self, client, app, auth_headers, tenant):
        from app.crypto.probe_crypto import generate_x25519_keypair, generate_ed25519_keypair
        with app.app_context():
            _, sign_pub = generate_ed25519_keypair()
            _, exchange_pub = generate_x25519_keypair()

        probe_id = self._register(client, auth_headers, tenant, machine_id="crypto-test-02")
        resp = client.post(
            "/api/v1/probe/provision-keys",
            json={
                "probe_id": probe_id,
                "probe_sign_public_key": sign_pub.hex(),
                "probe_exchange_public_key": exchange_pub.hex(),
            },
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert "server_sign_public_key" in data
        assert "server_exchange_public_key" in data
        assert "fingerprint" in data

    def test_provision_keys_twice_fails(self, client, app, auth_headers, tenant):
        from app.crypto.probe_crypto import generate_x25519_keypair, generate_ed25519_keypair
        with app.app_context():
            _, sign_pub = generate_ed25519_keypair()
            _, exchange_pub = generate_x25519_keypair()

        probe_id = self._register(client, auth_headers, tenant, machine_id="crypto-test-03")
        payload = {
            "probe_id": probe_id,
            "probe_sign_public_key": sign_pub.hex(),
            "probe_exchange_public_key": exchange_pub.hex(),
        }
        resp1 = client.post("/api/v1/probe/provision-keys", json=payload)
        assert resp1.status_code == 200
        resp2 = client.post("/api/v1/probe/provision-keys", json=payload)
        assert resp2.status_code == 400


class TestHeartbeat:
    def test_heartbeat(self, client, auth_headers, tenant):
        resp = client.post(
            "/api/v1/probe-tokens",
            json={"tenant_id": tenant["id"]},
            headers=auth_headers,
        )
        token = resp.get_json()["token"]
        reg = client.post(
            "/api/v1/probe/register",
            json={"registration_token": token, "hostname": "hb-probe.local", "machine_id": "hb-001"},
        )
        probe_id = reg.get_json()["probe_id"]

        hb = client.post(
            "/api/v1/probe/heartbeat",
            json={"probe_id": probe_id, "metrics": {"cpu_seconds": 10, "memory_mb": 256}},
            headers=auth_headers,
        )
        assert hb.status_code == 200
        assert hb.get_json()["status"] == "online"
