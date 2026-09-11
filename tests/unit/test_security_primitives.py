import pytest

from app.errors import SecurityError, ValidationError
from app.security.crypto import CredentialCipher, derive_fernet_key
from app.security.passwords import hash_password, validate_password_policy, verify_password
from app.security.validators import (
    parse_semver,
    validate_app_code,
    validate_hostname,
    validate_image_name,
    validate_ip_address,
    validate_port,
    validate_relative_path,
    validate_url_path,
)


def test_cipher_roundtrip_and_rotation():
    cipher = CredentialCipher("first-key-material-that-is-long-enough-0001")
    token = cipher.encrypt("s3cret")
    assert token != "s3cret"
    assert cipher.decrypt(token) == "s3cret"
    rotated = CredentialCipher(
        "second-key-material-that-is-long-enough-02",
        previous_key="first-key-material-that-is-long-enough-0001",
    )
    assert rotated.decrypt(token) == "s3cret"
    new_token = rotated.rotate(token)
    assert (
        CredentialCipher("second-key-material-that-is-long-enough-02").decrypt(new_token)
        == "s3cret"
    )
    with pytest.raises(SecurityError):
        CredentialCipher("unrelated-key-material-that-is-long-enough").decrypt(token)


def test_fernet_key_accepted_directly():
    key = CredentialCipher.generate_key()
    assert derive_fernet_key(key) == key.encode()
    assert CredentialCipher(key).decrypt(CredentialCipher(key).encrypt("x")) == "x"


def test_password_hashing():
    hashed = hash_password("Correct-Horse-Battery-9")
    assert hashed.startswith("$argon2")
    assert verify_password(hashed, "Correct-Horse-Battery-9")
    assert not verify_password(hashed, "wrong")


@pytest.mark.parametrize(
    "password", ["short", "alllowercaseletters", "password1234", "Username-Based-99"]
)
def test_password_policy_rejects(password):
    with pytest.raises(ValidationError):
        validate_password_policy(password, username="username")


def test_password_policy_accepts():
    validate_password_policy("Str0ng-Passw0rd!x", username="admin")


def test_hostname_validation():
    assert validate_hostname("prod-app-01.example.internal") == "prod-app-01.example.internal"
    for bad in ["", "-bad", "a b", "host;rm", "localhost", "x" * 254]:
        with pytest.raises(ValidationError):
            validate_hostname(bad)


def test_ip_validation():
    assert validate_ip_address("10.1.2.3") == "10.1.2.3"
    assert validate_ip_address("fd00::1") == "fd00::1"
    assert validate_ip_address("") is None
    for bad in ["127.0.0.1", "224.0.0.1", "0.0.0.0", "999.1.1.1", "1.2.3.4; ls"]:
        with pytest.raises(ValidationError):
            validate_ip_address(bad)


def test_port_validation():
    assert validate_port("22") == 22
    for bad in [0, 70000, "abc", -1]:
        with pytest.raises(ValidationError):
            validate_port(bad)


def test_app_code_and_semver():
    assert validate_app_code("Customer-API") == "customer-api"
    for bad in ["1app", "app_x", "app--x", "app/x", "app x", ""]:
        with pytest.raises(ValidationError):
            validate_app_code(bad)
    parsed = parse_semver("2.5.0-rc.1+build.7")
    assert (
        parsed["major"],
        parsed["minor"],
        parsed["patch"],
        parsed["prerelease"],
        parsed["build_metadata"],
    ) == (2, 5, 0, "rc.1", "build.7")
    for bad in ["1.0", "v1.0.0", "1.0.0 && x", "01.0.0"]:
        with pytest.raises(ValidationError):
            parse_semver(bad)


def test_image_name_validation():
    assert validate_image_name("registry.example.internal:5000/team/app")
    for bad in ["Team/App", "app; rm", "app:tag", "$(id)"]:
        with pytest.raises(ValidationError):
            validate_image_name(bad)


def test_relative_and_url_paths():
    assert validate_relative_path("scripts/run.sh") == "scripts/run.sh"
    for bad in ["/abs", "../x", "a/../b", "a//b", "scripts/run;sh"]:
        with pytest.raises(ValidationError):
            validate_relative_path(bad)
    assert validate_url_path("/health?x=1") == "/health?x=1"
    for bad in ["health", "/a b", "/x/../y", "/x;id"]:
        with pytest.raises(ValidationError):
            validate_url_path(bad)
