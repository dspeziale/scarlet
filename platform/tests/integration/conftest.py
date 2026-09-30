"""Test di integrazione con Docker reale (Linux).

Abilitati con APPCTL_INTEGRATION=1. Usano:
* un registry locale (registry:2) su 127.0.0.1:5001, per testare pull e "registry non disponibile";
* l'immagine dell'applicazione (APPCTL_TEST_IMAGE, altrimenti costruita dal repository);
* varianti dell'immagine: "unhealthy" (SCARLET_SIMULATE_UNHEALTHY) e "crash" (entrypoint che esce).
"""

from __future__ import annotations

import os
import shutil
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from helpers import (  # noqa: E402
    APP_NAME,
    APP_PORT,
    ENABLED,
    REGISTRY,
    REGISTRY_NAME,
    REGISTRY_PORT,
    REPO,
    TAG_A,
    TAG_B,
    TAG_BAD,
    TAG_BROKEN,
    TAG_CRASH,
    Appctl,
    build_image,
    sh,
)


def pytest_collection_modifyitems(config, items):
    if ENABLED:
        return
    skip = pytest.mark.skip(reason="test di integrazione: APPCTL_INTEGRATION=1 e Linux con Docker")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def registry():
    sh("docker", "rm", "-f", REGISTRY_NAME, check=False)
    sh(
        "docker", "run", "-d", "--name", REGISTRY_NAME,
        "-p", f"127.0.0.1:{REGISTRY_PORT}:5000", "registry:2",
    )  # fmt: skip
    for _ in range(30):
        if sh("curl", "-fs", f"http://{REGISTRY}/v2/", check=False).returncode == 0:
            break
        time.sleep(1)
    else:
        raise RuntimeError("registry locale non partito")
    yield REGISTRY
    sh("docker", "rm", "-f", REGISTRY_NAME, check=False)


@pytest.fixture(scope="session")
def images(registry):
    base = os.environ.get("APPCTL_TEST_IMAGE")
    if base:
        # immagine gia' costruita dalla CI: variante A con metadati di versione noti
        a = build_image(
            TAG_A,
            "",
            base=base,
            extra=(
                "ENV APP_VERSION=1.0.0-it APP_COMMIT=aaaaaaaaaaaa\n"
                "LABEL org.opencontainers.image.version=1.0.0-it "
                "org.opencontainers.image.revision=aaaaaaaaaaaa"
            ),
        )
    else:
        a = build_image(TAG_A, "1.0.0-it")
    # variante B: stessi layer di A con metadati di versione diversi (build immediata)
    b = build_image(
        TAG_B,
        "",
        base=a,
        extra=(
            "ENV APP_VERSION=1.1.0-it APP_COMMIT=bbbbbbbbbbbb\n"
            "LABEL org.opencontainers.image.version=1.1.0-it "
            "org.opencontainers.image.revision=bbbbbbbbbbbb"
        ),
    )
    bad = build_image(TAG_BAD, "", base=a, extra="ENV SCARLET_SIMULATE_UNHEALTHY=true")
    # crash: le migrazioni funzionano, il server termina subito (porta non valida) -> crash loop
    crash = build_image(TAG_CRASH, "", base=a, extra="ENV SCARLET_BIND_PORT=non-e-una-porta")
    # broken: entrypoint rotto, fallisce gia' il comando di migrazione
    broken = build_image(
        TAG_BROKEN,
        "",
        base=a,
        extra='ENTRYPOINT ["python", "-c", "import sys; print(1); sys.exit(3)"]',
    )
    return {"a": a, "b": b, "bad": bad, "crash": crash, "broken": broken}


@pytest.fixture
def app_dir(tmp_path: Path, images):
    d = tmp_path / "apps" / APP_NAME
    (d / "config").mkdir(parents=True)
    (d / "secrets").mkdir()
    (d / "data" / "postgres").mkdir(parents=True)
    # PostgreSQL gira come uid 999: la directory dati deve appartenergli
    sh(
        "docker",
        "run",
        "--rm",
        "-v",
        f"{d / 'data' / 'postgres'}:/d",
        "alpine:3.20",
        "chown",
        "999:999",
        "/d",
    )
    (d / "app.conf").write_text(
        "\n".join(
            [
                f"APP_NAME={APP_NAME}",
                "APP_ENVIRONMENT=development",
                f"IMAGE_REPOSITORY={REPO}",
                "COMPOSE_FILES=compose.yaml:compose.db.yaml",
                "DB_SERVICE=db",
                f"APP_PORT={APP_PORT}",
                "MIGRATE_COMMAND=alembic upgrade head",
                "HEALTH_TIMEOUT=90",
                "HEALTH_INTERVAL=2",
                "KEEP_RELEASES=3",
                "BACKUP_BEFORE_MIGRATE=true",
                f"AUDIT_LOG={d / 'audit.log'}",
                "",
            ]
        )
    )
    (d / "config" / "app.env").write_text(
        "SCARLET_ENVIRONMENT=development\nSCARLET_LOG_LEVEL=INFO\n"
    )
    secrets = d / "secrets" / "app.secrets.env"
    secrets.write_text(
        "POSTGRES_USER=scarlet\nPOSTGRES_PASSWORD=it-secret\nPOSTGRES_DB=scarlet\n"
        "SCARLET_DATABASE_URL=postgresql+psycopg://scarlet:it-secret@db:5432/scarlet\n"
        "SCARLET_API_TOKEN=it-token\n"
    )
    secrets.chmod(0o600)
    yield d
    # pulizia: container del project compose e directory dati (owner 999)
    sh("docker", "rm", "-f", f"{APP_NAME}-app", f"{APP_NAME}-db", check=False)
    sh("docker", "network", "rm", f"{APP_NAME}_default", check=False)
    sh("docker", "run", "--rm", "-v", f"{d}:/d", "alpine:3.20", "rm", "-rf", "/d/data", check=False)
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def appctl(app_dir: Path) -> Appctl:
    return Appctl(app_dir)
