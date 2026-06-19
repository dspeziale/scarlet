"""Central configuration — all settings loaded from environment variables."""

import os
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()


class Config:
    # ── Flask ──────────────────────────────────────────────────────────────
    SECRET_KEY: str = os.environ.get("SECRET_KEY", "change-me-in-production")
    DEBUG: bool = False
    TESTING: bool = False

    # ── Database ───────────────────────────────────────────────────────────
    SQLALCHEMY_DATABASE_URI: str = os.environ.get(
        "DATABASE_URL", "postgresql://localhost/soc_seattle"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS: bool = False
    SQLALCHEMY_ENGINE_OPTIONS: dict = {
        "pool_pre_ping": True,
        "pool_recycle": 300,
        "connect_args": {"sslmode": "require"} if "neon" in os.environ.get("DATABASE_URL", "") else {},
    }

    # ── JWT ────────────────────────────────────────────────────────────────
    JWT_SECRET_KEY: str = os.environ.get("JWT_SECRET_KEY", SECRET_KEY)
    JWT_ACCESS_TOKEN_EXPIRES: timedelta = timedelta(minutes=15)
    JWT_REFRESH_TOKEN_EXPIRES: timedelta = timedelta(days=30)
    JWT_ALGORITHM: str = "HS256"
    JWT_TOKEN_LOCATION: list = ["headers"]
    JWT_HEADER_NAME: str = "Authorization"
    JWT_HEADER_TYPE: str = "Bearer"
    JWT_BLACKLIST_ENABLED: bool = True

    # ── Rate limiting ──────────────────────────────────────────────────────
    RATELIMIT_DEFAULT: str = "200 per day;50 per hour"
    RATELIMIT_STORAGE_URI: str = os.environ.get("REDIS_URL", "memory://")
    RATELIMIT_HEADERS_ENABLED: bool = True

    # ── CORS ───────────────────────────────────────────────────────────────
    CORS_ORIGINS: list = os.environ.get("CORS_ORIGINS", "*").split(",")

    # ── Security headers ───────────────────────────────────────────────────
    TALISMAN_FORCE_HTTPS: bool = os.environ.get("FORCE_HTTPS", "false").lower() == "true"
    TALISMAN_CONTENT_SECURITY_POLICY: dict = {
        "default-src": "'self'",
        "script-src": ["'self'", "cdn.jsdelivr.net", "vercel.live", "'unsafe-inline'"],
        "style-src": ["'self'", "cdn.jsdelivr.net", "fonts.googleapis.com", "'unsafe-inline'"],
        "img-src": ["'self'", "data:", "cdn.jsdelivr.net"],
        "font-src": ["'self'", "cdn.jsdelivr.net", "fonts.gstatic.com"],
        # connect-src governs XHR/fetch and devtools source-map (.map) requests.
        "connect-src": ["'self'", "cdn.jsdelivr.net", "vercel.live"],
        # frame-src: Vercel live-feedback iframe (preview deployments only).
        "frame-src": ["'self'", "vercel.live"],
    }

    # ── Probe registration tokens ──────────────────────────────────────────
    PROBE_TOKEN_EXPIRY_HOURS: int = int(os.environ.get("PROBE_TOKEN_EXPIRY_HOURS", "24"))

    # ── Crypto ────────────────────────────────────────────────────────────
    KEY_ROTATION_DAYS: int = int(os.environ.get("KEY_ROTATION_DAYS", "30"))

    # ── Logging ───────────────────────────────────────────────────────────
    LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "INFO")
    LOG_FORMAT: str = os.environ.get("LOG_FORMAT", "json")


class DevelopmentConfig(Config):
    DEBUG = True
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "pool_recycle": 300,
    }
    TALISMAN_FORCE_HTTPS = False


class TestingConfig(Config):
    TESTING = True
    DEBUG = True
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "TEST_DATABASE_URL", "sqlite:///:memory:"
    )
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(minutes=5)
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False
    SQLALCHEMY_ENGINE_OPTIONS = {}


class ProductionConfig(Config):
    TALISMAN_FORCE_HTTPS = True


_configs = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
    "default": DevelopmentConfig,
}


def get_config(env: str | None = None) -> type[Config]:
    key = env or os.environ.get("FLASK_ENV", "default")
    return _configs.get(key, DevelopmentConfig)
