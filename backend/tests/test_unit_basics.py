"""Config, quantities, names, passwords, rate limiter, logging."""

from __future__ import annotations

import json
import logging
from decimal import Decimal

import pytest

from pkm.config import ConfigError, Settings, load_settings
from pkm.errors import ValidationFailed
from pkm.k8s.naming import is_label, is_subdomain, validate_name
from pkm.k8s.quantity import bytes_, cpu_cores, is_valid_cpu, is_valid_memory, parse_quantity
from pkm.logging_setup import JsonFormatter, TextFormatter, request_id_var, setup_logging
from pkm.security.passwords import hash_password, needs_rehash, password_problems, verify_password
from pkm.security.ratelimit import RateLimiter
from pkm.security.rbac import Perm, has_perm, permissions_for


# ------------------------------------------------------------------ config
def test_defaults_are_production_live():
    s = Settings()
    assert s.mode == "live" and s.environment == "production"
    assert not s.server.tls_enabled
    assert s.cookie_secure is False


def test_demo_refused_in_production():
    with pytest.raises(ValueError, match="demo"):
        Settings(mode="demo", environment="production")


def test_tls_pair_required():
    with pytest.raises(ValueError, match="tls_cert"):
        Settings(server={"tls_cert": "/a.crt"})
    s = Settings(server={"tls_cert": "/a.crt", "tls_key": "/a.key"})
    assert s.server.tls_enabled and s.cookie_secure


def test_cookie_secure_with_proxy_and_override():
    assert Settings(server={"trusted_proxies": ["127.0.0.1"]}).cookie_secure
    assert Settings(auth={"cookie_secure": False}, server={"tls_cert": "a", "tls_key": "b"}).cookie_secure is False


def test_prometheus_url_validation():
    with pytest.raises(ValueError):
        Settings(monitoring={"prometheus_url": "ftp://x"})
    assert Settings(monitoring={"prometheus_url": "http://p:9090/"}).monitoring.prometheus_url == "http://p:9090"
    assert Settings(monitoring={"prometheus_url": ""}).monitoring.prometheus_url is None


def test_load_settings_yaml_and_env(tmp_path, monkeypatch):
    f = tmp_path / "c.yaml"
    f.write_text("server:\n  port: 9000\n  host: 0.0.0.0\napp_name: Test\n", encoding="utf-8")
    monkeypatch.setenv("PKM_SERVER__PORT", "9443")
    s = load_settings(str(f))
    assert s.server.port == 9443  # env wins over file
    assert s.server.host == "0.0.0.0"
    assert s.app_name == "Test"
    assert s.config_file == str(f)


def test_load_settings_from_env_var_path(tmp_path, monkeypatch):
    f = tmp_path / "c.yaml"
    f.write_text("mode: live\n", encoding="utf-8")
    monkeypatch.setenv("PKM_CONFIG", str(f))
    assert load_settings().config_file == str(f)


@pytest.mark.parametrize("content,msg", [
    ("server: [unclosed", "invalid YAML"),
    ("- a\n- b\n", "must contain a mapping"),
    ("server:\n  port: 99999\n", "server.port"),
    ("mode: demo\n", "demo"),
])
def test_load_settings_errors(tmp_path, content, msg):
    f = tmp_path / "c.yaml"
    f.write_text(content, encoding="utf-8")
    with pytest.raises(ConfigError, match=msg):
        load_settings(str(f))


def test_load_settings_missing_file(tmp_path):
    with pytest.raises(ConfigError, match="cannot read"):
        load_settings(str(tmp_path / "nope.yaml"))


# ------------------------------------------------------------------ quantity
@pytest.mark.parametrize("value,expected", [
    ("250m", Decimal("0.25")), ("1", Decimal(1)), ("1.5", Decimal("1.5")), ("1Gi", Decimal(2**30)),
    ("128974848", Decimal(128974848)), ("1k", Decimal(1000)), ("100Mi", Decimal(100 * 2**20)), (2, Decimal(2)),
])
def test_parse_quantity(value, expected):
    assert parse_quantity(value) == expected


def test_parse_quantity_invalid():
    assert parse_quantity(None) is None
    assert parse_quantity("abc") is None
    assert parse_quantity("1Xi") is None


def test_cpu_bytes_helpers():
    assert cpu_cores("500m") == 0.5
    assert bytes_("1Ki") == 1024
    assert cpu_cores(None) is None and bytes_("x") is None
    assert is_valid_cpu("250m") and is_valid_cpu("0.5") and not is_valid_cpu("0") and not is_valid_cpu("1Gi")
    assert is_valid_memory("256Mi") and is_valid_memory("1G") and not is_valid_memory("1.5Gi") and not is_valid_memory("0")


# ------------------------------------------------------------------ naming
def test_names():
    assert is_label("web-prod") and not is_label("Web") and not is_label("-a") and not is_label("a" * 64)
    assert is_subdomain("a.b-c") and not is_subdomain("a..b")
    assert validate_name("ok") == "ok"
    with pytest.raises(ValidationFailed) as e:
        validate_name("Bad_Name", "metadata.name")
    assert e.value.params["field"] == "metadata.name"
    assert validate_name("a.b", subdomain=True) == "a.b"


# ------------------------------------------------------------------ passwords
def test_password_hash_roundtrip():
    h = hash_password("Correct-Horse-9")
    assert verify_password(h, "Correct-Horse-9")
    assert not verify_password(h, "wrong")
    assert not verify_password(None, "pkm-dummy-password-for-timing")
    assert not verify_password("not-a-hash", "x")
    assert needs_rehash(h) is False


@pytest.mark.parametrize("pw,problem", [
    ("Short1!", "too_short"), ("password123", "too_common"), ("aliceAlice123!", "contains_username"),
    ("alllowercaseletters", "not_enough_character_classes"), ("A" * 300 + "a1!", "too_long"),
])
def test_password_policy(pw, problem):
    assert problem in password_problems(pw, username="alice", min_length=12)


def test_password_policy_ok():
    assert password_problems("Str0ng-Passw0rd!", username="admin", min_length=12) == []


# ------------------------------------------------------------------ rate limiter / rbac
def test_rate_limiter():
    rl = RateLimiter(2, window_seconds=60)
    assert rl.hit("a") and rl.hit("a") and not rl.hit("a")
    assert rl.retry_after("a") >= 1
    assert rl.retry_after("unknown") == 0
    rl.reset("a")
    assert rl.hit("a")


def test_rate_limiter_eviction():
    rl = RateLimiter(1, window_seconds=0.0, max_keys=3)
    for i in range(10):
        assert rl.hit(f"k{i}")
    assert len(rl._hits) <= 3


def test_rbac():
    assert has_perm("admin", Perm.USERS_MANAGE)
    assert not has_perm("operator", Perm.USERS_MANAGE)
    assert has_perm("operator", Perm.WORKLOADS_SCALE)
    assert not has_perm("viewer", Perm.LOGS_READ)
    assert not has_perm("ghost", Perm.CLUSTER_READ)
    assert permissions_for("ghost") == []
    assert set(permissions_for("viewer")) < set(permissions_for("operator")) < set(permissions_for("admin"))


# ------------------------------------------------------------------ logging
def test_json_formatter_includes_request_id_and_extra():
    token = request_id_var.set("rid-12345678")
    try:
        rec = logging.LogRecord("pkm.test", logging.INFO, __file__, 1, "hello %s", ("world",), None)
        rec.custom = {"a": 1}
        out = json.loads(JsonFormatter().format(rec))
    finally:
        request_id_var.reset(token)
    assert out["message"] == "hello world" and out["request_id"] == "rid-12345678"
    assert out["component"] == "pkm.test" and out["custom"] == "{'a': 1}"
    text = TextFormatter().format(rec)
    assert "hello world" in text


def test_formatters_with_exception():
    try:
        raise ValueError("boom")
    except ValueError:
        import sys

        rec = logging.LogRecord("pkm", logging.ERROR, __file__, 1, "x", (), sys.exc_info())
    assert "boom" in json.loads(JsonFormatter().format(rec))["exception"]
    assert "boom" in TextFormatter().format(rec)


def test_setup_logging_file(tmp_path):
    from pkm.config import LoggingConfig

    setup_logging(LoggingConfig(level="INFO", file=str(tmp_path / "l" / "pkm.log"), json_format=False))
    logging.getLogger("pkm.t").info("to file")
    for h in logging.getLogger().handlers:
        h.flush()
    assert "to file" in (tmp_path / "l" / "pkm.log").read_text(encoding="utf-8")
    setup_logging(LoggingConfig(level="WARNING"))
