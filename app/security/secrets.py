"""SecretProvider abstraction.

The initial implementation stores secrets encrypted in PostgreSQL. The
interface is intentionally small so Vault / AWS Secrets Manager / Kubernetes
Secrets providers can be added without touching callers.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.security.crypto import CredentialCipher, get_cipher


class SecretProvider(ABC):
    """Stores and retrieves secret values by opaque reference."""

    name = "abstract"

    @abstractmethod
    def store(self, plaintext: str) -> str:
        """Persist ``plaintext`` and return an opaque reference (ciphertext or path)."""

    @abstractmethod
    def retrieve(self, reference: str) -> str:
        """Return the plaintext for ``reference``."""

    @abstractmethod
    def rotate(self, reference: str) -> str:
        """Re-protect the secret with the current key; return the new reference."""

    def delete(self, reference: str) -> None:  # noqa: B027 - optional hook
        """Remove the secret from the backend (no-op for inline ciphertext)."""


class EncryptedDatabaseSecretProvider(SecretProvider):
    """Secrets are Fernet ciphertext stored inline in the database row."""

    name = "encrypted-database"

    def __init__(self, cipher: CredentialCipher | None = None) -> None:
        self._cipher = cipher

    @property
    def cipher(self) -> CredentialCipher:
        return self._cipher or get_cipher()

    def store(self, plaintext: str) -> str:
        return self.cipher.encrypt(plaintext)

    def retrieve(self, reference: str) -> str:
        return self.cipher.decrypt(reference)

    def rotate(self, reference: str) -> str:
        return self.cipher.rotate(reference)


class VaultSecretProvider(SecretProvider):  # pragma: no cover - extension point
    """Placeholder for HashiCorp Vault KV v2. Not enabled by default."""

    name = "vault"

    def __init__(self, *args, **kwargs) -> None:
        raise NotImplementedError("Vault provider is not configured in this release.")

    def store(self, plaintext: str) -> str:
        raise NotImplementedError

    def retrieve(self, reference: str) -> str:
        raise NotImplementedError

    def rotate(self, reference: str) -> str:
        raise NotImplementedError


_PROVIDERS: dict[str, type[SecretProvider]] = {
    EncryptedDatabaseSecretProvider.name: EncryptedDatabaseSecretProvider,
    VaultSecretProvider.name: VaultSecretProvider,
}


def get_secret_provider(name: str | None = None) -> SecretProvider:
    from flask import current_app, has_app_context

    if has_app_context():
        provider = current_app.extensions.get("scarlet_secret_provider")
        if provider is not None and name is None:
            return provider
    provider_cls = _PROVIDERS.get(name or EncryptedDatabaseSecretProvider.name)
    if provider_cls is None:
        raise ValueError(f"Unknown secret provider {name!r}")
    provider = provider_cls()
    if has_app_context() and name is None:
        current_app.extensions["scarlet_secret_provider"] = provider
    return provider
