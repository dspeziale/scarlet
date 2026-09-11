"""Build SCARLET release packages from a source directory.

Used by ``scripts/build-scarlet-package.py`` and by the test-suite. The
resulting archive is always accepted by ``PackageValidator`` when the
manifest is valid: members are normalized, links are refused, permissions are
sanitized and a ``checksums.sha256`` file is generated.
"""

from __future__ import annotations

import hashlib
import io
import os
import tarfile
import time
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from app.deployment.manifest import Manifest, parse_manifest
from app.deployment.validator import ALLOWED_TOP_LEVEL, PackageValidator
from app.errors import PackageValidationError


@dataclass
class BuildResult:
    output_path: Path
    manifest: Manifest
    checksum_sha256: str
    size_bytes: int
    members: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def filename(self) -> str:
        return self.output_path.name


def package_filename(application: str, version: str) -> str:
    return f"{application}-{version}.scarlet.tar.gz"


def build_package(
    source_dir: str | Path,
    output_dir: str | Path,
    *,
    version: str | None = None,
    validate: bool = True,
) -> BuildResult:
    source = Path(source_dir).resolve()
    if not source.is_dir():
        raise PackageValidationError(f"Source directory {source} does not exist.")
    manifest_path = source / "manifest.yaml"
    if not manifest_path.is_file():
        raise PackageValidationError("manifest.yaml is missing in the source directory.")
    raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise PackageValidationError("manifest.yaml must be a mapping.")
    if version:
        raw["version"] = version
        image = raw.get("image")
        if isinstance(image, dict) and image.get("tag") in (None, "", "${VERSION}", "{{version}}"):
            image["tag"] = version
    manifest = parse_manifest(yaml.safe_dump(raw, sort_keys=False))
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    target = output / package_filename(manifest.application, manifest.version)

    members: list[str] = []
    warnings: list[str] = []
    checksums: list[str] = []
    files: list[tuple[str, Path]] = []
    for path in sorted(source.rglob("*")):
        rel = path.relative_to(source).as_posix()
        if path.is_symlink():
            warnings.append(f"skipped symlink {rel}")
            continue
        top = rel.split("/")[0]
        if top.startswith(".") or top in {"__pycache__", "dist", "node_modules"}:
            continue
        if top not in ALLOWED_TOP_LEVEL:
            warnings.append(
                f"unexpected top-level entry '{top}' included (allowed: {', '.join(sorted(ALLOWED_TOP_LEVEL))})"
            )
        if path.is_file():
            if rel == "manifest.yaml" or rel == "checksums.sha256":
                continue
            files.append((rel, path))

    manifest_bytes = yaml.safe_dump(manifest.to_dict(), sort_keys=False).encode("utf-8")

    def add_bytes(tar: tarfile.TarFile, name: str, data: bytes, mode: int = 0o644) -> None:
        info = tarfile.TarInfo(name)
        info.size = len(data)
        info.mtime = int(time.time())
        info.mode = mode
        info.uid = info.gid = 0
        info.uname = info.gname = "scarlet"
        tar.addfile(info, io.BytesIO(data))
        members.append(name)

    with tarfile.open(target, "w:gz", format=tarfile.PAX_FORMAT) as tar:
        add_bytes(tar, "manifest.yaml", manifest_bytes)
        checksums.append(f"{hashlib.sha256(manifest_bytes).hexdigest()}  manifest.yaml")
        for rel, path in files:
            data = path.read_bytes()
            mode = 0o755 if rel.startswith("scripts/") and rel.endswith(".sh") else 0o644
            add_bytes(tar, rel, data, mode)
            checksums.append(f"{hashlib.sha256(data).hexdigest()}  {rel}")
        add_bytes(tar, "checksums.sha256", ("\n".join(checksums) + "\n").encode("utf-8"))

    digest = hashlib.sha256()
    with open(target, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    result = BuildResult(
        output_path=target,
        manifest=manifest,
        checksum_sha256=digest.hexdigest(),
        size_bytes=os.path.getsize(target),
        members=members,
        warnings=warnings,
    )
    if validate:
        report = PackageValidator().validate_file(str(target), target.name)
        if not report.valid:
            target.unlink(missing_ok=True)
            raise PackageValidationError(
                "Built package failed validation: " + "; ".join(report.errors),
                errors={"package": report.errors},
            )
        result.warnings.extend(report.warnings)
    (output / f"{target.name}.sha256").write_text(
        f"{result.checksum_sha256}  {target.name}\n", encoding="utf-8"
    )
    return result
