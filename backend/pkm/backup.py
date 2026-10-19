"""Scarlet backup: what it is and what it is NOT.

A Scarlet backup archive (pkm-backup-<UTC timestamp>.tar.gz) contains:
  - pkm.db            consistent copy of the application database (users, audit log,
                      settings, notifications, backup history), made with the SQLite backup API
  - config/           files of the configuration directory when readable: config.yaml, pkm.env,
                      kubeconfig, tls/pkm.crt, tls/pkm.key (secrets: the archive is mode 0600)
  - k8s/ (optional)   "manifests export": YAML of namespaced application resources
                      (Deployments, StatefulSets, DaemonSets, CronJobs, Services, Ingresses,
                      ConfigMaps, PVC definitions, PDBs, HPAs, Namespaces). Secrets are NOT
                      exported. Persistent volume DATA and etcd are NOT included.
  - manifest.json     version, timestamp, content list with SHA-256 of every file

It is NOT a Kubernetes cluster backup: use etcd snapshots or Velero for that.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import socket
import sqlite3
import tarfile
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from . import __version__
from .db import Database, iso
from .errors import BadRequest, NotFound, ValidationFailed

log = logging.getLogger("pkm.backup")

FILENAME_RE = re.compile(r"^pkm-backup-\d{8}T\d{6}Z(?:-[a-z0-9]{1,16})?\.tar\.gz$")
EXPORT_KINDS = ["namespaces", "deployments", "statefulsets", "daemonsets", "cronjobs", "services", "ingresses",
                "configmaps", "persistentvolumeclaims", "poddisruptionbudgets", "horizontalpodautoscalers"]  # fmt: skip
SYSTEM_NAMESPACES = {"kube-system", "kube-public", "kube-node-lease"}
# Besides config.yaml, these files of the configuration directory are saved when present.
CONFIG_EXTRA_FILES = ("pkm.env", "kubeconfig", "tls/pkm.crt", "tls/pkm.key")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _clean_for_export(obj: dict[str, Any]) -> dict[str, Any]:
    o = json.loads(json.dumps(obj))
    o.pop("status", None)
    meta = o.get("metadata") or {}
    for f in ("uid", "resourceVersion", "creationTimestamp", "managedFields", "generation", "selfLink",
              "ownerReferences"):  # fmt: skip
        meta.pop(f, None)
    ann = meta.get("annotations") or {}
    ann.pop("kubectl.kubernetes.io/last-applied-configuration", None)
    ann.pop("deployment.kubernetes.io/revision", None)
    if not ann:
        meta.pop("annotations", None)
    if o.get("kind") == "Service":
        spec = o.get("spec") or {}
        for f in ("clusterIP", "clusterIPs"):
            spec.pop(f, None)
    if o.get("kind") == "PersistentVolumeClaim":
        (o.get("spec") or {}).pop("volumeName", None)
    return o


class BackupService:
    def __init__(self, db: Database, directory: str, config_file: str | None) -> None:
        self.db = db
        self.dir = Path(directory)
        self.config_file = config_file

    def _path(self, filename: str) -> Path:
        if not FILENAME_RE.match(filename):
            raise ValidationFailed("invalid backup file name", params={"field": "filename"})
        p = (self.dir / filename).resolve()
        if p.parent != self.dir.resolve():
            raise ValidationFailed("invalid backup file name", params={"field": "filename"})
        return p

    # ---------------------------------------------------------------- create
    def create(self, *, trigger: str, user: str, include_manifests: bool = False,
               k8s: Any = None, progress: Any = None) -> dict[str, Any]:  # fmt: skip
        self.dir.mkdir(parents=True, exist_ok=True)
        os.chmod(self.dir, 0o700)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        suffix = "" if trigger == "manual" else f"-{trigger}"
        filename = f"pkm-backup-{stamp}{suffix}.tar.gz"
        target = self.dir / filename
        includes = ["database"]
        with self.db.connect() as c:
            cur = c.execute(
                "INSERT INTO backups(filename, created_at, status, trigger, created_by) VALUES (?,?,?,?,?)",
                (filename, iso(), "running", trigger, user),
            )
            backup_id = cur.lastrowid
        step = progress or (lambda *_a, **_k: None)
        try:
            with tempfile.TemporaryDirectory(prefix="pkm-backup-", dir=str(self.dir)) as tmp:
                work = Path(tmp)
                self.db.backup_to(str(work / "pkm.db"))
                step("database", {})
                files: dict[str, str] = {"pkm.db": _sha256(work / "pkm.db")}
                cfg_dir = work / "config"
                if self.config_file and Path(self.config_file).is_file():
                    cfg_dir.mkdir()
                    base = Path(self.config_file).parent
                    for rel in (Path(self.config_file).name, *CONFIG_EXTRA_FILES):
                        src = base / rel
                        if not src.is_file():
                            continue
                        dest = cfg_dir / rel
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        try:
                            shutil.copyfile(src, dest)
                        except OSError:
                            continue
                        files[f"config/{rel}"] = _sha256(dest)
                    includes.append("config")
                    step("config", {})
                export_errors: list[str] = []
                if include_manifests and k8s is not None:
                    count, export_errors = self._export_manifests(k8s, work / "k8s", files)
                    includes.append("k8s_manifests")
                    step("k8s_manifests", {"objects": count, "errors": export_errors})
                manifest = {"format": 1, "application": "pkm", "version": __version__, "created_at": iso(),
                            "hostname": socket.gethostname(), "schema_version": self.db.schema_version(),
                            "includes": includes, "files": files, "export_errors": export_errors,
                            "notice": "Not a Kubernetes cluster backup: no etcd, no persistent volume data, "
                                      "no Secrets."}  # fmt: skip
                (work / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
                partial = target.with_suffix(".partial")
                fd = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with os.fdopen(fd, "wb") as fh, tarfile.open(fileobj=fh, mode="w:gz") as tar:
                    for p in sorted(work.rglob("*")):
                        if p.is_file():
                            tar.add(p, arcname=str(p.relative_to(work)).replace("\\", "/"))
                os.replace(partial, target)
            digest = _sha256(target)
            Path(str(target) + ".sha256").write_text(f"{digest}  {filename}\n", encoding="utf-8")
            size = target.stat().st_size
            with self.db.connect() as c:
                c.execute("UPDATE backups SET status='success', size_bytes=?, sha256=?, includes=? WHERE id=?",
                          (size, digest, json.dumps(includes), backup_id))  # fmt: skip
            log.info("backup created", extra={"file": filename, "size": size})
            return self.get(filename)
        except Exception as exc:
            with self.db.connect() as c:
                c.execute("UPDATE backups SET status='failed', detail=? WHERE id=?", (str(exc)[:1000], backup_id))
            target.with_suffix(".partial").unlink(missing_ok=True)
            log.exception("backup failed")
            raise

    def _export_manifests(self, k8s: Any, root: Path, files: dict[str, str]) -> tuple[int, list[str]]:
        from .errors import AppError
        from .k8s.kinds import KINDS

        count = 0
        errors: list[str] = []
        for key in EXPORT_KINDS:
            kind = KINDS[key]
            try:
                items = k8s.list_raw(kind)
            except AppError as exc:
                errors.append(f"{key}: {exc.message}")
                continue
            for obj in items:
                meta = obj.get("metadata") or {}
                ns = meta.get("namespace") or ("_cluster" if not kind.namespaced else "")
                if ns in SYSTEM_NAMESPACES or (key == "namespaces" and meta.get("name") in SYSTEM_NAMESPACES):
                    continue
                rel = f"k8s/{ns or '_cluster'}/{kind.key}/{meta.get('name')}.yaml"
                path = root.parent / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(yaml.safe_dump(_clean_for_export(obj), sort_keys=False), encoding="utf-8")
                files[rel] = _sha256(path)
                count += 1
        return count, errors

    # ---------------------------------------------------------------- query
    def list(self) -> list[dict[str, Any]]:
        with self.db.connect() as c:
            rows = [dict(r) for r in c.execute("SELECT * FROM backups WHERE status != 'deleted' ORDER BY id DESC")]
        for r in rows:
            r["includes"] = json.loads(r["includes"] or "[]")
            r["present"] = (self.dir / r["filename"]).is_file()
        known = {r["filename"] for r in rows}
        # Archives copied into the directory by hand or by restore.sh are listed as well.
        if self.dir.is_dir():
            for p in sorted(self.dir.glob("pkm-backup-*.tar.gz"), reverse=True):
                if p.name not in known and FILENAME_RE.match(p.name):
                    rows.append({"id": None, "filename": p.name, "created_at": datetime.fromtimestamp(
                        p.stat().st_mtime, UTC).isoformat(timespec="seconds"), "size_bytes": p.stat().st_size,
                        "sha256": "", "status": "success", "trigger": "external", "created_by": "",
                        "includes": [], "verified_at": None, "verify_result": None, "detail": "", "present": True})  # fmt: skip
        return rows

    def get(self, filename: str) -> dict[str, Any]:
        for r in self.list():
            if r["filename"] == filename:
                return r
        raise NotFound("backup not found")

    def last(self) -> dict[str, Any] | None:
        for r in self.list():
            if r["status"] == "success":
                return r
        return None

    def file_path(self, filename: str) -> Path:
        p = self._path(filename)
        if not p.is_file():
            raise NotFound("backup file not found")
        return p

    # ---------------------------------------------------------------- verify
    def verify_file(self, path: Path) -> dict[str, Any]:
        checks: list[dict[str, Any]] = []
        ok = True
        sidecar = Path(str(path) + ".sha256")
        digest = _sha256(path)
        if sidecar.is_file():
            expected = sidecar.read_text(encoding="utf-8").split()[0]
            match = expected == digest
            checks.append({"id": "archive_checksum", "status": "ok" if match else "fail"})
            ok &= match
        else:
            checks.append({"id": "archive_checksum", "status": "unknown"})
        manifest: dict[str, Any] = {}
        try:
            with tempfile.TemporaryDirectory(prefix="pkm-verify-") as tmp, tarfile.open(path, "r:gz") as tar:
                for member in tar.getmembers():
                    if member.name.startswith(("/", "..")) or ".." in Path(member.name).parts or not (
                            member.isfile() or member.isdir()):  # fmt: skip
                        raise ValidationFailed(f"unsafe path in archive: {member.name}")
                tar.extractall(tmp, filter="data")
                work = Path(tmp)
                manifest = json.loads((work / "manifest.json").read_text(encoding="utf-8"))
                checks.append({"id": "manifest", "status": "ok", "params": {"version": manifest.get("version")}})
                bad = [f for f, h in manifest.get("files", {}).items()
                       if not (work / f).is_file() or _sha256(work / f) != h]  # fmt: skip
                checks.append({"id": "file_checksums", "status": "fail" if bad else "ok", "params": {"bad": bad}})
                ok &= not bad
                conn = sqlite3.connect(str(work / "pkm.db"))
                try:
                    res = conn.execute("PRAGMA integrity_check").fetchone()[0]
                    users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
                finally:
                    conn.close()
                checks.append({"id": "database_integrity", "status": "ok" if res == "ok" else "fail",
                               "params": {"result": res, "users": users}})  # fmt: skip
                ok &= res == "ok"
        except (tarfile.TarError, OSError, EOFError, ValueError, KeyError, sqlite3.Error, ValidationFailed) as exc:
            checks.append({"id": "archive_readable", "status": "fail", "params": {"error": str(exc)[:300]}})
            ok = False
        return {"ok": ok, "sha256": digest, "checks": checks, "manifest": manifest}

    def verify(self, filename: str) -> dict[str, Any]:
        result = self.verify_file(self.file_path(filename))
        with self.db.connect() as c:
            c.execute("UPDATE backups SET verified_at=?, verify_result=? WHERE filename=?",
                      (iso(), "ok" if result["ok"] else "failed", filename))  # fmt: skip
        return result

    # ---------------------------------------------------------------- retention
    def apply_retention(self, keep: int) -> list[str]:
        rows = [r for r in self.list() if r["status"] == "success" and r["present"] and r["id"] is not None]
        removed = []
        for r in rows[keep:]:
            p = self._path(r["filename"])
            p.unlink(missing_ok=True)
            Path(str(p) + ".sha256").unlink(missing_ok=True)
            with self.db.connect() as c:
                c.execute("UPDATE backups SET status='deleted' WHERE filename=?", (r["filename"],))
            removed.append(r["filename"])
        return removed

    def delete(self, filename: str) -> None:
        p = self.file_path(filename)
        p.unlink()
        Path(str(p) + ".sha256").unlink(missing_ok=True)
        with self.db.connect() as c:
            c.execute("UPDATE backups SET status='deleted' WHERE filename=?", (filename,))


def restore_archive(archive: Path, db_path: str, *, config_dir: str | None, with_config: bool) -> dict[str, Any]:
    """Restore the database (and optionally the config files). The service MUST be stopped.

    The current database is kept as <db>.pre-restore-<timestamp>.
    """
    svc = BackupService(Database(":memory:"), str(archive.parent), None)
    result = svc.verify_file(archive)
    if not result["ok"]:
        raise BadRequest("backup verification failed: restore aborted", params={"checks": result["checks"]})
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    restored = []
    with tempfile.TemporaryDirectory(prefix="pkm-restore-") as tmp, tarfile.open(archive, "r:gz") as tar:
        tar.extractall(tmp, filter="data")
        work = Path(tmp)
        db = Path(db_path)
        if db.exists():
            shutil.copy2(db, db.with_name(f"{db.name}.pre-restore-{stamp}"))
        for suffix in ("-wal", "-shm"):
            Path(str(db) + suffix).unlink(missing_ok=True)
        tmp_db = db.with_name(db.name + ".restoring")
        shutil.copyfile(work / "pkm.db", tmp_db)
        os.replace(tmp_db, db)
        restored.append(str(db))
        if with_config and config_dir and (work / "config").is_dir():
            src_root = work / "config"
            for f in sorted(p for p in src_root.rglob("*") if p.is_file()):
                dest = Path(config_dir) / f.relative_to(src_root)
                dest.parent.mkdir(parents=True, exist_ok=True)
                if dest.exists():
                    shutil.copy2(dest, dest.with_name(f"{dest.name}.pre-restore-{stamp}"))
                shutil.copyfile(f, dest)
                restored.append(str(dest))
    return {"restored": restored, "verification": result, "previous_suffix": f".pre-restore-{stamp}"}
