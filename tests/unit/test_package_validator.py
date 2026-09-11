import io
import tarfile

import pytest

from app.deployment.validator import PackageValidator, is_safe_member_name, safe_extract

MANIFEST = b"""manifest_version: 1
application: customer-api
version: 1.0.0
runtime: podman
image:
  name: company/customer-api
  tag: 1.0.0
"""


def make_tar(path, members, *, manifest=MANIFEST, mode="w:gz"):
    with tarfile.open(path, mode) as tar:
        if manifest is not None:
            info = tarfile.TarInfo("manifest.yaml")
            info.size = len(manifest)
            tar.addfile(info, io.BytesIO(manifest))
        for member in members:
            if isinstance(member, tarfile.TarInfo):
                tar.addfile(member, io.BytesIO(b"x" * member.size) if member.isfile() else None)
            else:
                name, data = member
                info = tarfile.TarInfo(name)
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
    return path


def test_valid_package(tmp_path):
    path = make_tar(
        tmp_path / "customer-api-1.0.0.scarlet.tar.gz", [("application/app.txt", b"hello")]
    )
    report = PackageValidator().validate_file(str(path), path.name)
    assert report.valid, report.errors
    assert report.manifest.version == "1.0.0"
    assert report.checksum_sha256


def test_missing_manifest(tmp_path):
    path = make_tar(
        tmp_path / "x.scarlet.tar.gz", [("application/app.txt", b"hello")], manifest=None
    )
    report = PackageValidator().validate_file(str(path), path.name)
    assert not report.valid
    assert any("manifest.yaml is missing" in e for e in report.errors)


@pytest.mark.parametrize(
    "name", ["../../etc/passwd", "/etc/passwd", "application/../../x", "..", "C:\\windows\\x"]
)
def test_path_traversal_rejected(tmp_path, name):
    assert not is_safe_member_name(name)
    path = make_tar(tmp_path / "evil.scarlet.tar.gz", [(name, b"pwn")])
    report = PackageValidator().validate_file(str(path), path.name)
    assert not report.valid
    assert any("Unsafe path" in e for e in report.errors)


def test_symlink_rejected(tmp_path):
    link = tarfile.TarInfo("application/link")
    link.type = tarfile.SYMTYPE
    link.linkname = "/etc/passwd"
    path = make_tar(tmp_path / "link.scarlet.tar.gz", [link])
    report = PackageValidator().validate_file(str(path), path.name)
    assert not report.valid
    assert any("Links are not allowed" in e for e in report.errors)


def test_device_node_rejected(tmp_path):
    dev = tarfile.TarInfo("application/dev")
    dev.type = tarfile.CHRTYPE
    path = make_tar(tmp_path / "dev.scarlet.tar.gz", [dev])
    report = PackageValidator().validate_file(str(path), path.name)
    assert not report.valid


def test_setuid_rejected(tmp_path):
    info = tarfile.TarInfo("scripts/run.sh")
    info.size = 3
    info.mode = 0o4755
    path = make_tar(tmp_path / "suid.scarlet.tar.gz", [info])
    report = PackageValidator().validate_file(str(path), path.name)
    assert not report.valid
    assert any("setuid" in e for e in report.errors)


def test_wrong_extension_and_not_gzip(tmp_path):
    path = tmp_path / "package.zip"
    path.write_bytes(b"PK\x03\x04")
    report = PackageValidator().validate_file(str(path), path.name)
    assert not report.valid
    fake = tmp_path / "fake.scarlet.tar.gz"
    fake.write_bytes(b"not a gzip at all")
    report = PackageValidator().validate_file(str(fake), fake.name)
    assert any("gzip" in e for e in report.errors)


def test_too_many_members(tmp_path):
    path = make_tar(
        tmp_path / "many.scarlet.tar.gz", [(f"application/f{i}.txt", b"x") for i in range(30)]
    )
    report = PackageValidator(max_members=10).validate_file(str(path), path.name)
    assert not report.valid
    assert any("more than 10 members" in e for e in report.errors)


def test_required_files_from_manifest(tmp_path):
    manifest = MANIFEST + b"hooks:\n  pre_deploy:\n    - scripts/pre.sh\n"
    path = make_tar(tmp_path / "hooks.scarlet.tar.gz", [], manifest=manifest)
    report = PackageValidator().validate_file(str(path), path.name)
    assert not report.valid
    assert any("scripts/pre.sh" in e for e in report.errors)
    ok = make_tar(
        tmp_path / "hooks-ok.scarlet.tar.gz",
        [("scripts/pre.sh", b"#!/bin/sh\n")],
        manifest=manifest,
    )
    assert PackageValidator().validate_file(str(ok), ok.name).valid


def test_unknown_top_level_is_warning_not_error(tmp_path):
    path = make_tar(tmp_path / "w.scarlet.tar.gz", [("weird/file.txt", b"x")])
    report = PackageValidator().validate_file(str(path), path.name)
    assert report.valid
    assert any("Unexpected top-level" in w for w in report.warnings)


def test_safe_extract(tmp_path):
    path = make_tar(
        tmp_path / "ok.scarlet.tar.gz",
        [("application/app.txt", b"hello"), ("kubernetes/deploy.yaml", b"kind: Deployment")],
    )
    dest = tmp_path / "out"
    extracted = safe_extract(str(path), str(dest))
    assert (dest / "application" / "app.txt").read_bytes() == b"hello"
    assert "kubernetes/deploy.yaml" in extracted
