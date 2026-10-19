"""Backups include the whole configuration directory needed for disaster recovery."""

from __future__ import annotations

import tarfile
from pathlib import Path

from pkm.backup import BackupService, restore_archive
from pkm.db import Database


def _setup(tmp_path: Path) -> tuple[Database, Path, Path]:
    etc = tmp_path / "etc"
    (etc / "tls").mkdir(parents=True)
    (etc / "config.yaml").write_text("mode: live\n", encoding="utf-8")
    (etc / "pkm.env").write_text("PKM_X=1\n", encoding="utf-8")
    (etc / "kubeconfig").write_text("apiVersion: v1\nkind: Config\n", encoding="utf-8")
    (etc / "tls" / "pkm.crt").write_text("CERT\n", encoding="utf-8")
    (etc / "tls" / "pkm.key").write_text("KEY\n", encoding="utf-8")
    db = Database(str(tmp_path / "data" / "pkm.db"))
    db.migrate()
    return db, etc, tmp_path / "backups"


def test_backup_contains_tls_and_kubeconfig(tmp_path: Path) -> None:
    db, etc, bdir = _setup(tmp_path)
    res = BackupService(db, str(bdir), str(etc / "config.yaml")).create(trigger="manual", user="t")
    with tarfile.open(bdir / res["filename"]) as tar:
        names = set(tar.getnames())
    assert {"config/config.yaml", "config/pkm.env", "config/kubeconfig", "config/tls/pkm.crt",
            "config/tls/pkm.key"} <= names  # fmt: skip
    assert BackupService(db, str(bdir), None).verify(res["filename"])["ok"]


def test_restore_with_config_recreates_nested_files(tmp_path: Path) -> None:
    db, etc, bdir = _setup(tmp_path)
    res = BackupService(db, str(bdir), str(etc / "config.yaml")).create(trigger="manual", user="t")
    (etc / "tls" / "pkm.key").write_text("CHANGED\n", encoding="utf-8")
    (etc / "kubeconfig").unlink()
    out = restore_archive(bdir / res["filename"], db.path, config_dir=str(etc), with_config=True)
    assert (etc / "tls" / "pkm.key").read_text(encoding="utf-8") == "KEY\n"
    assert (etc / "kubeconfig").is_file()
    assert any(p.name.startswith("pkm.key.pre-restore-") for p in (etc / "tls").iterdir())
    assert str(etc / "tls" / "pkm.key") in out["restored"]
