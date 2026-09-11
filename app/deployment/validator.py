"""Release package validation.

The archive is *never* extracted blindly. Members are inspected one by one:
absolute paths, ``..`` components, symlinks/hardlinks, device nodes, oversized
members and excessive member counts are rejected before anything is written
to disk. Only after the archive passes is the manifest read (in memory).
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import tarfile
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

from app.deployment.manifest import Manifest, parse_manifest
from app.errors import PackageValidationError
from app.security.validators import validate_path_segment

PACKAGE_SUFFIXES = (".scarlet.tar.gz", ".tar.gz", ".tgz")
MANIFEST_NAME = "manifest.yaml"
ALLOWED_TOP_LEVEL = {
    "manifest.yaml",
    "application",
    "docker-compose.yml",
    "docker-compose.yaml",
    "compose.yml",
    "compose.yaml",
    "Containerfile",
    "Dockerfile",
    "helm",
    "kubernetes",
    "scripts",
    "config",
    "README.md",
    "CHANGELOG.md",
    "LICENSE",
    "checksums.sha256",
}
GZIP_MAGIC = b"\x1f\x8b"


@dataclass
class ValidationReport:
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    manifest: Manifest | None = None
    manifest_text: str = ""
    checksum_sha256: str = ""
    size_bytes: int = 0
    file_count: int = 0
    uncompressed_bytes: int = 0
    members: list[str] = field(default_factory=list)
    scanner_result: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "errors": self.errors,
            "warnings": self.warnings,
            "manifest": self.manifest.to_dict() if self.manifest else None,
            "checksum_sha256": self.checksum_sha256,
            "size_bytes": self.size_bytes,
            "file_count": self.file_count,
            "uncompressed_bytes": self.uncompressed_bytes,
            "scanner_result": self.scanner_result,
        }


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_safe_member_name(name: str) -> bool:
    if not name or "\x00" in name:
        return False
    normalized = name.replace("\\", "/")
    if normalized.startswith("/") or normalized.startswith("~"):
        return False
    parts = [p for p in normalized.split("/") if p not in ("", ".")]
    if not parts and normalized not in (".", "./"):
        return False
    for part in parts:
        if part == "..":
            return False
        try:
            validate_path_segment(part, field="member")
        except Exception:  # noqa: BLE001
            return False
    # Windows drive letters
    return not (len(normalized) > 1 and normalized[1] == ":")


def normalize_member_name(name: str) -> str:
    normalized = name.replace("\\", "/")
    parts = [p for p in normalized.split("/") if p not in ("", ".")]
    return "/".join(parts)


class PackageValidator:
    def __init__(
        self,
        *,
        max_members: int = 20000,
        max_uncompressed_bytes: int = 8 * 1024 * 1024 * 1024,
        max_member_bytes: int = 4 * 1024 * 1024 * 1024,
        scanner_command: str | None = None,
    ) -> None:
        self.max_members = max_members
        self.max_uncompressed_bytes = max_uncompressed_bytes
        self.max_member_bytes = max_member_bytes
        self.scanner_command = scanner_command

    # --- public API ------------------------------------------------------------------
    def validate_file(self, path: str, original_filename: str | None = None) -> ValidationReport:
        report = ValidationReport(valid=False)
        report.size_bytes = os.path.getsize(path)
        report.checksum_sha256 = sha256_file(path)

        if original_filename is not None and not original_filename.lower().endswith(
            PACKAGE_SUFFIXES
        ):
            report.errors.append(
                f"Unexpected file extension for '{original_filename}'. Expected .scarlet.tar.gz"
            )
            return report

        with open(path, "rb") as fh:
            if fh.read(2) != GZIP_MAGIC:
                report.errors.append("File is not a gzip compressed archive.")
                return report

        try:
            with tarfile.open(path, mode="r:gz") as tar:
                self._inspect_members(tar, report)
                if report.errors:
                    return report
                self._read_manifest(tar, report)
        except tarfile.TarError as exc:
            report.errors.append(f"Archive is corrupt or not a tar.gz file: {exc}")
            return report
        except EOFError:
            report.errors.append("Archive is truncated.")
            return report
        except OSError as exc:
            report.errors.append(f"Archive could not be read: {exc}")
            return report

        if report.errors:
            return report

        self._check_required_files(report)
        if self.scanner_command:
            self._scan(path, report)
        report.valid = not report.errors
        return report

    # --- internals ---------------------------------------------------------------------
    def _inspect_members(self, tar: tarfile.TarFile, report: ValidationReport) -> None:
        seen: set[str] = set()
        count = 0
        total = 0
        top_level_unknown: set[str] = set()
        for member in tar:
            count += 1
            if count > self.max_members:
                report.errors.append(f"Archive contains more than {self.max_members} members.")
                return
            name = member.name
            if not is_safe_member_name(name):
                report.errors.append(f"Unsafe path in archive: {name!r}")
                return
            normalized = normalize_member_name(name)
            if not normalized:
                continue
            if member.issym() or member.islnk():
                report.errors.append(f"Links are not allowed in packages: {normalized}")
                return
            if member.isdev() or member.isfifo() or member.ischr() or member.isblk():
                report.errors.append(f"Special files are not allowed in packages: {normalized}")
                return
            if not (member.isfile() or member.isdir()):
                report.errors.append(f"Unsupported archive member type: {normalized}")
                return
            if member.isfile():
                if member.size > self.max_member_bytes:
                    report.errors.append(f"Member {normalized} exceeds the maximum size.")
                    return
                total += member.size
                if total > self.max_uncompressed_bytes:
                    report.errors.append("Uncompressed package size exceeds the configured limit.")
                    return
                if member.mode & 0o6000:
                    report.errors.append(f"setuid/setgid bits are not allowed: {normalized}")
                    return
            if normalized in seen:
                report.warnings.append(f"Duplicate member in archive: {normalized}")
            seen.add(normalized)
            top = normalized.split("/")[0]
            if top not in ALLOWED_TOP_LEVEL:
                top_level_unknown.add(top)
            report.members.append(normalized)
        report.file_count = count
        report.uncompressed_bytes = total
        if MANIFEST_NAME not in seen:
            report.errors.append("manifest.yaml is missing from the package root.")
        for top in sorted(top_level_unknown):
            report.warnings.append(
                f"Unexpected top-level entry '{top}' (allowed: {', '.join(sorted(ALLOWED_TOP_LEVEL))})."
            )

    def _read_manifest(self, tar: tarfile.TarFile, report: ValidationReport) -> None:
        member = None
        for candidate in tar.getmembers():
            if normalize_member_name(candidate.name) == MANIFEST_NAME and candidate.isfile():
                member = candidate
                break
        if member is None:
            report.errors.append("manifest.yaml is missing from the package root.")
            return
        if member.size > 256 * 1024:
            report.errors.append("manifest.yaml is too large (max 256 KiB).")
            return
        handle = tar.extractfile(member)
        if handle is None:
            report.errors.append("manifest.yaml could not be read.")
            return
        raw = handle.read(member.size)
        try:
            report.manifest = parse_manifest(raw)
            report.manifest_text = raw.decode("utf-8")
        except PackageValidationError as exc:
            report.errors.extend(
                exc.errors.get("manifest", [exc.message]) if exc.errors else [exc.message]
            )

    def _check_required_files(self, report: ValidationReport) -> None:
        manifest = report.manifest
        if manifest is None:
            return
        members = set(report.members)
        dirs = {m for m in members}
        for m in report.members:
            parent = PurePosixPath(m).parent
            while str(parent) not in ("", "."):
                dirs.add(str(parent))
                parent = parent.parent
        for required in manifest.required_files():
            if required not in members:
                report.errors.append(
                    f"Required file '{required}' declared in manifest is missing from the package."
                )
        for required in manifest.required_dirs():
            if required not in dirs:
                report.errors.append(
                    f"Required directory '{required}' declared in manifest is missing from the package."
                )
        if manifest.compose and manifest.compose.file not in members:
            report.errors.append(f"Compose file '{manifest.compose.file}' is missing.")
        scripts = [m for m in report.members if m.startswith("scripts/") and m.endswith(".sh")]
        declared = set(manifest.hooks.all_scripts())
        for script in scripts:
            if script not in declared:
                report.warnings.append(
                    f"Script '{script}' is not referenced by any hook and will never run."
                )

    def _scan(self, path: str, report: ValidationReport) -> None:
        """Optional external malware scanner (e.g. ``clamscan --no-summary {path}``)."""
        assert self.scanner_command
        argv = [part.replace("{path}", path) for part in self.scanner_command.split()]
        try:
            proc = subprocess.run(
                argv, capture_output=True, text=True, timeout=600, check=False
            )  # noqa: S603
        except (OSError, subprocess.TimeoutExpired) as exc:
            report.errors.append(f"Malware scanner could not be executed: {exc}")
            report.scanner_result = "ERROR"
            return
        if proc.returncode == 0:
            report.scanner_result = "CLEAN"
        else:
            report.scanner_result = "INFECTED" if proc.returncode == 1 else "ERROR"
            report.errors.append("Malware scanner rejected the package.")


def build_validator_from_config(config) -> PackageValidator:
    return PackageValidator(
        max_members=int(config.get("SCARLET_MAX_PACKAGE_MEMBERS", 20000)),
        max_uncompressed_bytes=int(config.get("SCARLET_MAX_PACKAGE_UNCOMPRESSED_MB", 8192))
        * 1024
        * 1024,
        scanner_command=config.get("SCARLET_MALWARE_SCANNER_COMMAND") or None,
    )


def safe_extract(archive_path: str, destination: str, *, max_members: int = 20000) -> list[str]:
    """Extract a previously validated archive to ``destination`` (local, for K8s API mode).

    Re-checks every member and never follows links.
    """
    extracted: list[str] = []
    dest_root = os.path.realpath(destination)
    os.makedirs(dest_root, exist_ok=True)
    with tarfile.open(archive_path, mode="r:gz") as tar:
        count = 0
        for member in tar:
            count += 1
            if count > max_members:
                raise PackageValidationError("Too many members in archive.")
            if not is_safe_member_name(member.name):
                raise PackageValidationError(f"Unsafe path in archive: {member.name!r}")
            if not (member.isfile() or member.isdir()):
                raise PackageValidationError(f"Unsupported member type: {member.name}")
            normalized = normalize_member_name(member.name)
            if not normalized:
                continue
            target = os.path.realpath(os.path.join(dest_root, *normalized.split("/")))
            if os.path.commonpath([dest_root, target]) != dest_root:
                raise PackageValidationError("Path traversal detected during extraction.")
            if member.isdir():
                os.makedirs(target, exist_ok=True)
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            source = tar.extractfile(member)
            if source is None:
                continue
            with open(target, "wb") as out:
                while True:
                    chunk = source.read(1024 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)
            os.chmod(target, 0o640)
            extracted.append(normalized)
    return extracted
