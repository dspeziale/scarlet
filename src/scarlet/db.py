"""Accesso al database (SQLAlchemy) e verifiche usate da /ready."""

from __future__ import annotations

import os
from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path

from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from scarlet.config import get_settings


def _find_alembic_ini() -> Path | None:
    """alembic.ini sta nella root del progetto (sviluppo) o in /app (dentro l'immagine)."""
    candidates = [
        os.environ.get("SCARLET_ALEMBIC_INI", ""),
        str(Path.cwd() / "alembic.ini"),
        str(Path(__file__).resolve().parents[2] / "alembic.ini"),
    ]
    for c in candidates:
        if c and Path(c).is_file():
            return Path(c)
    return None


ALEMBIC_INI = _find_alembic_ini()


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    url = get_settings().database_url
    kwargs: dict[str, object] = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    return create_engine(url, **kwargs)


@lru_cache(maxsize=1)
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def get_session() -> Iterator[Session]:
    session = get_sessionmaker()()
    try:
        yield session
    finally:
        session.close()


def reset_engine_cache() -> None:
    """Usato dai test."""
    get_engine.cache_clear()
    get_sessionmaker.cache_clear()


@lru_cache(maxsize=1)
def expected_schema_revision() -> str | None:
    """Revisione Alembic attesa (head) secondo le migrazioni distribuite con il codice."""
    if ALEMBIC_INI is None:
        return None
    cfg = AlembicConfig(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(ALEMBIC_INI.parent / "migrations"))
    return ScriptDirectory.from_config(cfg).get_current_head()


def check_database() -> dict[str, object]:
    """Ritorna lo stato del DB per /ready: raggiungibilita' e allineamento schema."""
    result: dict[str, object] = {"ok": False, "reachable": False, "schema": "unknown"}
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
            result["reachable"] = True
            try:
                row = conn.execute(text("SELECT version_num FROM alembic_version")).first()
            except Exception:  # tabella assente: schema mai migrato
                row = None
    except Exception as exc:  # DB non raggiungibile
        result["error"] = f"{type(exc).__name__}: {exc}"[:300]
        return result

    current = row[0] if row else None
    expected = expected_schema_revision()
    result["schema"] = current or "not-migrated"
    result["expected_schema"] = expected
    result["ok"] = current is not None and (expected is None or current == expected)
    if not result["ok"]:
        result["error"] = "schema non allineato: eseguire le migrazioni (alembic upgrade head)"
    return result
