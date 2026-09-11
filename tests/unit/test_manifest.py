import pytest

from app.deployment.manifest import parse_manifest
from app.errors import ManifestValidationError

BASE = """
manifest_version: 1
application: customer-api
version: 2.5.0
runtime: podman
image:
  name: company/customer-api
  tag: 2.5.0
ports:
  - container: 8080
healthcheck:
  type: http
  path: /health
  port: 8080
"""


def test_valid_manifest_parses():
    manifest = parse_manifest(BASE)
    assert manifest.application == "customer-api"
    assert manifest.version == "2.5.0"
    assert manifest.image.reference == "company/customer-api:2.5.0"
    assert manifest.ports[0].as_publish_arg() == "8080:8080"
    assert manifest.runtime_type == "PODMAN"


@pytest.mark.parametrize(
    "replacement,expected",
    [
        ("manifest_version: 1", "manifest_version: 99"),
        ("application: customer-api", "application: Customer API"),
        ("version: 2.5.0", "version: v2.5"),
        ("runtime: podman", "runtime: lxc"),
        ("  name: company/customer-api", "  name: company/customer api; rm -rf /"),
        ("  tag: 2.5.0", "  tag: '2.5.0 && reboot'"),
        ("  path: /health", "  path: /health; id"),
    ],
)
def test_invalid_values_rejected(replacement, expected):
    text = BASE.replace(replacement, expected)
    with pytest.raises(ManifestValidationError):
        parse_manifest(text)


def test_unknown_fields_rejected():
    with pytest.raises(ManifestValidationError):
        parse_manifest(BASE + "\nextra_field: 1\n")


def test_image_or_compose_required_for_containers():
    text = BASE.replace("image:\n  name: company/customer-api\n  tag: 2.5.0\n", "")
    with pytest.raises(ManifestValidationError):
        parse_manifest(text)


def test_reserved_environment_keys_rejected():
    with pytest.raises(ManifestValidationError):
        parse_manifest(BASE + "\nenvironment:\n  SCARLET_VERSION: x\n")


def test_hooks_must_be_scripts_under_scripts_dir():
    with pytest.raises(ManifestValidationError):
        parse_manifest(BASE + "\nhooks:\n  pre_deploy:\n    - ../evil.sh\n")
    with pytest.raises(ManifestValidationError):
        parse_manifest(BASE + "\nhooks:\n  pre_deploy:\n    - config/run.sh\n")
    manifest = parse_manifest(BASE + "\nhooks:\n  pre_deploy:\n    - scripts/pre.sh\n")
    assert manifest.hooks.pre_deploy == ["scripts/pre.sh"]
    assert "scripts/pre.sh" in manifest.required_files()


def test_kubernetes_requires_section():
    text = BASE.replace("runtime: podman", "runtime: kubernetes").replace(
        "image:\n  name: company/customer-api\n  tag: 2.5.0\n", ""
    )
    with pytest.raises(ManifestValidationError):
        parse_manifest(text)
    ok = parse_manifest(text + "\nkubernetes:\n  namespace: apps\n  manifests: kubernetes\n")
    assert ok.healthcheck.type == "http"
    assert "kubernetes" in ok.required_dirs()


def test_volume_mount_validation():
    with pytest.raises(ManifestValidationError):
        parse_manifest(BASE + "\nvolumes:\n  - name: data\n    mount: ../etc\n")
    with pytest.raises(ManifestValidationError):
        parse_manifest(BASE + "\nvolumes:\n  - name: data\n    mount: /data:Z\n")


def test_duplicate_host_ports_rejected():
    with pytest.raises(ManifestValidationError):
        parse_manifest(
            BASE.replace(
                "ports:\n  - container: 8080\n",
                "ports:\n  - container: 8080\n  - container: 9090\n    host: 8080\n",
            )
        )


def test_healthcheck_command_rejects_shell_metacharacters():
    with pytest.raises(ManifestValidationError):
        parse_manifest(BASE.replace("type: http", "type: command\n  command: 'true; rm -rf /'"))


def test_manifest_not_yaml_mapping():
    with pytest.raises(ManifestValidationError):
        parse_manifest("- just\n- a list\n")
    with pytest.raises(ManifestValidationError):
        parse_manifest(b"\xff\xfe not utf8")
