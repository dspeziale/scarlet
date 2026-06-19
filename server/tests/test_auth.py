"""Tests for authentication endpoints."""

import pytest


class TestLogin:
    def test_login_success(self, client, db):
        resp = client.post("/api/v1/auth/login", json={"email": "admin@test.local", "password": "Admin123!"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["user"]["email"] == "admin@test.local"

    def test_login_wrong_password(self, client, db):
        resp = client.post("/api/v1/auth/login", json={"email": "admin@test.local", "password": "wrong"})
        assert resp.status_code == 401

    def test_login_unknown_email(self, client, db):
        resp = client.post("/api/v1/auth/login", json={"email": "nobody@nowhere.com", "password": "x"})
        assert resp.status_code == 401

    def test_login_missing_fields(self, client, db):
        resp = client.post("/api/v1/auth/login", json={"email": "admin@test.local"})
        assert resp.status_code == 400

    def test_login_empty_body(self, client, db):
        resp = client.post("/api/v1/auth/login", json={})
        assert resp.status_code == 400


class TestMe:
    def test_me_authenticated(self, client, auth_headers):
        resp = client.get("/api/v1/auth/me", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["email"] == "admin@test.local"
        assert data["is_superadmin"] is True

    def test_me_unauthenticated(self, client):
        resp = client.get("/api/v1/auth/me")
        assert resp.status_code == 401


class TestLogout:
    def test_logout(self, client, db):
        # Login first
        resp = client.post("/api/v1/auth/login", json={"email": "admin@test.local", "password": "Admin123!"})
        token = resp.get_json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Logout
        resp2 = client.delete("/api/v1/auth/logout", headers=headers)
        assert resp2.status_code == 200

        # Token should now be rejected
        resp3 = client.get("/api/v1/auth/me", headers=headers)
        assert resp3.status_code == 401


class TestRefresh:
    def test_refresh_token(self, client, db):
        resp = client.post("/api/v1/auth/login", json={"email": "admin@test.local", "password": "Admin123!"})
        refresh_token = resp.get_json()["refresh_token"]
        resp2 = client.post("/api/v1/auth/refresh", headers={"Authorization": f"Bearer {refresh_token}"})
        assert resp2.status_code == 200
        assert "access_token" in resp2.get_json()
