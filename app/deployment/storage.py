"""Artifact storage abstraction.

Package bytes never live in PostgreSQL. ``LocalFilesystemArtifactStorage`` is
the default implementation; S3/MinIO providers can implement the same interface.

Layout::

    <root>/<application_id>/<version>/package.tar.gz
    <root>/<application_id>/<version>/manifest.yaml
    <root>/<application_id>/<version>/metadata.json
    <root>/_incoming/<random>.tar.gz          (uploads not yet validated)
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO

from app.errors import ArtifactStorageError
from app.security.validators import validate_path_segment
from app.utils.ids import new_token

CHUNK = 1024 * 1024


@dataclass(frozen=True)
class StoredArtifact:
    storage_key: str
    size_bytes: int
    checksum_sha256: str


class ArtifactStorage(ABC):
    """Interface for artifact backends."""

    @abstractmethod
    def store_incoming(self, stream: BinaryIO, *, max_bytes: int) -> StoredArtifact:
        """Stream an upload into a temporary (incoming) location, hashing on the fly."""

    @abstractmethod
    def promote(self, incoming_key: str, application_id: int, version: str, manifest_yaml: str, metadata: dict[str, Any]) -> StoredArtifact:
        """Move a validated incoming artifact to its immutable release location."""

    @abstractmethod
    def open(self, storage_key: str) -> BinaryIO: ...

    @abstractmethod
    def local_path(self, storage_key: str) -> str:
        """Return a local filesystem path for the artifact (downloading if remote)."""

    @abstractmethod
    def delete(self, storage_key: str) -> None: ...

    @abstractmethod
    def exists(self, storage_key: str) -> bool: ...

    @abstractmethod
    def size(self, storage_key: str) -> int: ...

    @abstractmethod
    def iter_incoming(self) -> Iterator[tuple[str, float]]:
        """Yield (storage_key, mtime) for incoming (unpromoted) artifacts."""

    @abstractmethod
    def checksum(self, storage_key: str) -> str: ...


class LocalFilesystemArtifactStorage(ArtifactStorage):
    INCOMING = "_incoming"

    def __init__(self, root: str) -> None:
        self.root = Path(root).resolve()
        (self.root / self.INCOMING).mkdir(parents=True, exist_ok=True)

    # --- helpers -------------------------------------------------------------------
    def _resolve(self, storage_key: str) -> Path:
        if not storage_key or storage_key.startswith(("/", "\\")) or ".." in Path(storage_key).parts:
            raise ArtifactStorageError("Invalid storage key.")
        path = (self.root / storage_key).resolve()
        if self.root not in path.parents:
            raise ArtifactStorageError("Storage key escapes the artifact root.")
        return path

    # --- interface -----------------------------------------------------------------
    def store_incoming(self, stream: BinaryIO, *, max_bytes: int) -> StoredArtifact:
        key = f"{self.INCOMING}/{new_token(16)}.tar.gz"
        path = self._resolve(key)
        digest = hashlib.sha256()
        size = 0
        try:
            with open(path, "wb") as out:
                while True:
                    chunk = stream.read(CHUNK)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > max_bytes:
                        raise ArtifactStorageError(
                            f"Upload exceeds the maximum allowed size of {max_bytes // (1024 * 1024)} MB."
                        )
                    digest.update(chunk)
                    out.write(chunk)
        except Exception:
            path.unlink(missing_ok=True)
            raise
        if size == 0:
            path.unlink(missing_ok=True)
            raise ArtifactStorageError("Uploaded file is empty.")
        return StoredArtifact(key, size, digest.hexdigest())

    def promote(self, incoming_key: str, application_id: int, version: str, manifest_yaml: str, metadata: dict[str, Any]) -> StoredArtifact:
        src = self._resolve(incoming_key)
        if not src.exists():
            raise ArtifactStorageError("Incoming artifact not found.")
        validate_path_segment(version, field="version")
        target_dir = self._resolve(f"{int(application_id)}/{version}")
        if target_dir.exists():
            raise ArtifactStorageError(
                f"Release {version} already exists in artifact storage (releases are immutable)."
            )
        target_dir.mkdir(parents=True, exist_ok=False)
        dest = target_dir / "package.tar.gz"
        shutil.move(str(src), str(dest))
        (target_dir / "manifest.yaml").write_text(manifest_yaml, encoding="utf-8")
        (target_dir / "metadata.json").write_text(json.dumps(metadata, indent=2, default=str), encoding="utf-8")
        # make the release read-only where the platform supports it
        try:
            os.chmod(dest, 0o440)
        except OSError:  # pragma: no cover
            pass
        key = f"{int(application_id)}/{version}/package.tar.gz"
        return StoredArtifact(key, dest.stat().st_size, self.checksum(key))

    def open(self, storage_key: str) -> BinaryIO:
        path = self._resolve(storage_key)
        if not path.is_file():
            raise ArtifactStorageError("Artifact not found.")
        return open(path, "rb")

    def local_path(self, storage_key: str) -> str:
        path = self._resolve(storage_key)
        if not path.is_file():
            raise ArtifactStorageError("Artifact not found.")
        return str(path)

    def delete(self, storage_key: str) -> None:
        path = self._resolve(storage_key)
        if path.is_file():
            try:
                os.chmod(path, 0o640)
            except OSError:  # pragma: no cover
                pass
            path.unlink()
            parent = path.parent
            if parent != self.root and parent.name != self.INCOMING and not any(parent.iterdir()):
                parent.rmdir()

    def delete_release(self, application_id: int, version: str) -> None:
        validate_path_segment(version, field="version")
        target_dir = self._resolve(f"{int(application_id)}/{version}")
        if target_dir.is_dir():
            for child in target_dir.iterdir():
                try:
                    os.chmod(child, 0o640)
                except OSError:  # pragma: no cover
                    pass
            shutil.rmtree(target_dir)

    def exists(self, storage_key: str) -> bool:
        return self._resolve(storage_key).is_file()

    def size(self, storage_key: str) -> int:
        return self._resolve(storage_key).stat().st_size

    def iter_incoming(self) -> Iterator[tuple[str, float]]:
        incoming = self.root / self.INCOMING
        for entry in incoming.iterdir():
            if entry.is_file():
                yield f"{self.INCOMING}/{entry.name}", entry.stat().st_mtime

    def checksum(self, storage_key: str) -> str:
        digest = hashlib.sha256()
        with self.open(storage_key) as fh:
            for chunk in iter(lambda: fh.read(CHUNK), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def usage_bytes(self) -> int:
        total = 0
        for path in self.root.rglob("*"):
            if path.is_file():
                total += path.stat().st_size
        return total


def get_artifact_storage() -> ArtifactStorage:
    from flask import current_app

    storage = current_app.extensions.get("scarlet_artifact_storage")
    if storage is None:
        storage = LocalFilesystemArtifactStorage(current_app.config["SCARLET_ARTIFACT_PATH"])
        current_app.extensions["scarlet_artifact_storage"] = storage
    return storage
