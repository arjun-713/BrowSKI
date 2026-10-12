"""Local credential storage with no plaintext-file fallback."""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Protocol, cast

_SERVICE_NAME = "browski"
_OPENAI_ACCOUNT = "openai-api-key"
_MAX_API_KEY_LENGTH = 4_096


class CredentialStoreError(RuntimeError):
    """Raised when the operating-system credential store is unavailable."""


class CredentialStore(Protocol):
    """Minimal secret-store interface used by the runtime and tests."""

    def get_openai_api_key(self) -> str | None: ...

    def set_openai_api_key(self, api_key: str) -> None: ...

    def delete_openai_api_key(self) -> None: ...


class _KeyringModule(Protocol):
    def get_password(self, service_name: str, username: str) -> object | None: ...

    def set_password(self, service_name: str, username: str, password: str) -> None: ...

    def delete_password(self, service_name: str, username: str) -> None: ...


class SystemCredentialStore:
    """Store credentials in the user's configured OS keyring backend."""

    def __init__(self, keyring_module: _KeyringModule | None = None) -> None:
        self._keyring_module = keyring_module

    def get_openai_api_key(self) -> str | None:
        keyring = self._keyring()
        try:
            value = keyring.get_password(_SERVICE_NAME, _OPENAI_ACCOUNT)
        except Exception:
            raise CredentialStoreError(
                "the system credential store could not read BROWSKI credentials"
            ) from None
        if value is None:
            return None
        if not isinstance(value, str) or not value or len(value) > _MAX_API_KEY_LENGTH:
            raise CredentialStoreError("the stored BROWSKI credential is invalid")
        return value

    def set_openai_api_key(self, api_key: str) -> None:
        if not api_key or len(api_key) > _MAX_API_KEY_LENGTH or "\n" in api_key or "\r" in api_key:
            raise ValueError("the OpenAI API key is outside supported limits")
        keyring = self._keyring()
        try:
            keyring.set_password(_SERVICE_NAME, _OPENAI_ACCOUNT, api_key)
        except Exception:
            raise CredentialStoreError(
                "the system credential store could not save BROWSKI credentials"
            ) from None

    def delete_openai_api_key(self) -> None:
        keyring = self._keyring()
        try:
            existing_value = keyring.get_password(_SERVICE_NAME, _OPENAI_ACCOUNT)
            if existing_value is None:
                return
            keyring.delete_password(_SERVICE_NAME, _OPENAI_ACCOUNT)
        except Exception:
            raise CredentialStoreError(
                "the system credential store could not remove BROWSKI credentials"
            ) from None

    def _keyring(self) -> _KeyringModule:
        if self._keyring_module is not None:
            return self._keyring_module
        try:
            import keyring
        except ImportError:
            raise CredentialStoreError(
                "install the system-keyring extra to configure credentials from BROWSKI"
            ) from None
        keyring_module = cast(_KeyringModule, keyring)
        self._keyring_module = keyring_module
        return keyring_module


def configured_openai_api_key() -> str | None:
    """Return an environment override or a keyring credential, if available."""
    environment_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("BROWSKI_OPENAI_API_KEY")
    if environment_key:
        return environment_key
    try:
        return SystemCredentialStore().get_openai_api_key()
    except CredentialStoreError:
        return None


def load_local_env_credentials(path: Path) -> None:
    """Explicit launcher support for the user's owner-only local .env file.

    Read only the two supported credential variables. Existing environment
    credentials take precedence. Never evaluate shell syntax or expand values.
    This does not create a plaintext fallback for the OS credential store.
    """
    names = ("OPENAI_API_KEY", "BROWSKI_OPENAI_API_KEY")
    if any(os.environ.get(name) for name in names) or not path.exists():
        return
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "r", encoding="utf-8") as file:
        info = os.fstat(file.fileno())
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_mode & 0o077
            or info.st_size > 65536
        ):
            raise CredentialStoreError("local .env must be an owner-only bounded regular file")
        for line in file:
            name, separator, value = line.strip().partition("=")
            if not separator or name not in names:
                continue
            value = value.strip()
            if len(value) >= 2 and value[0] in {"'", '"'} and value[-1] == value[0]:
                value = value[1:-1]
            if not value or len(value) > _MAX_API_KEY_LENGTH or any(c.isspace() for c in value):
                raise CredentialStoreError("local credential is outside supported limits")
            os.environ[name] = value
