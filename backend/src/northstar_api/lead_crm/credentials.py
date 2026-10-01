from __future__ import annotations

import base64
import hashlib
import json
import os
from abc import ABC, abstractmethod
from typing import Any

from cryptography.fernet import Fernet, InvalidToken


class CredentialStoreError(RuntimeError):
    pass


class CredentialStore(ABC):
    @abstractmethod
    def encrypt(self, credentials: dict[str, Any]) -> bytes:
        raise NotImplementedError

    @abstractmethod
    def decrypt(self, encrypted: bytes) -> dict[str, Any]:
        raise NotImplementedError


class EncryptedDatabaseCredentialStore(CredentialStore):
    """Local encrypted credential backend.

    Production deployments should set CRM_CREDENTIAL_ENCRYPTION_KEY from a secret
    manager. The database stores only authenticated ciphertext. This class is the
    compatible local backend behind the CredentialStore interface; Vault/cloud
    secret-manager backends can replace it without changing connector services.
    """

    ENV_KEY = "CRM_CREDENTIAL_ENCRYPTION_KEY"

    def _fernet(self) -> Fernet:
        secret = os.getenv(self.ENV_KEY, "")
        if not secret:
            raise CredentialStoreError(f"{self.ENV_KEY} is not configured")
        digest = hashlib.sha256(secret.encode("utf-8")).digest()
        return Fernet(base64.urlsafe_b64encode(digest))

    def encrypt(self, credentials: dict[str, Any]) -> bytes:
        if not credentials:
            raise ValueError("credentials cannot be empty")
        raw = json.dumps(credentials, separators=(",", ":"), sort_keys=True).encode("utf-8")
        return self._fernet().encrypt(raw)

    def decrypt(self, encrypted: bytes) -> dict[str, Any]:
        try:
            raw = self._fernet().decrypt(encrypted)
            value = json.loads(raw)
        except (InvalidToken, json.JSONDecodeError) as exc:
            raise CredentialStoreError("Stored CRM credentials are unreadable") from exc
        if not isinstance(value, dict):
            raise CredentialStoreError("Stored CRM credentials have invalid structure")
        return {str(key): item for key, item in value.items()}


credential_store: CredentialStore = EncryptedDatabaseCredentialStore()
