"""Configurazione dell'applicazione: solo variabili d'ambiente, nessun file.

Le variabili applicative hanno prefisso ``SCARLET_``. Le informazioni di build
(``APP_VERSION``, ``APP_COMMIT``, ``APP_BUILD_TIME``, ``IMAGE``) sono impostate dal
Dockerfile e dal compose e non hanno prefisso perché sono uno standard di piattaforma.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SCARLET_", extra="ignore")

    environment: str = "development"
    database_url: str = "sqlite:///./scarlet.db"
    api_token: str = ""
    log_level: str = "INFO"
    log_format: str = "json"  # json | text
    # Solo per test di piattaforma: forza /health e /ready a 503 per simulare un deploy fallito.
    simulate_unhealthy: bool = False

    # Metadati di build (standard di piattaforma, senza prefisso)
    app_version: str = Field(
        default="0.0.0-dev",
        validation_alias=AliasChoices("APP_VERSION", "SCARLET_APP_VERSION"),
    )
    app_commit: str = Field(
        default="unknown",
        validation_alias=AliasChoices("APP_COMMIT", "SCARLET_APP_COMMIT"),
    )
    app_build_time: str = Field(
        default="unknown",
        validation_alias=AliasChoices("APP_BUILD_TIME", "SCARLET_APP_BUILD_TIME"),
    )
    image: str = Field(
        default="unknown",
        validation_alias=AliasChoices("IMAGE", "SCARLET_IMAGE"),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    """Usato dai test per ricaricare la configurazione dopo aver cambiato l'ambiente."""
    get_settings.cache_clear()
