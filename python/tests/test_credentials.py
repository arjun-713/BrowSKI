"""Credential storage must use the OS keyring and never persist plaintext files."""

from __future__ import annotations

import pytest

from browser_agent.credentials import (
    CredentialStoreError,
    SystemCredentialStore,
    configured_openai_api_key,
)


class FakeKeyring:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    def get_password(self, service_name: str, username: str) -> str | None:
        return self.values.get((service_name, username))

    def set_password(self, service_name: str, username: str, password: str) -> None:
        self.values[(service_name, username)] = password

    def delete_password(self, service_name: str, username: str) -> None:
        self.values.pop((service_name, username), None)


def test_keyring_store_sets_reads_and_deletes_credential() -> None:
    backend = FakeKeyring()
    store = SystemCredentialStore(backend)

    store.set_openai_api_key("secret-value")
    assert store.get_openai_api_key() == "secret-value"
    store.delete_openai_api_key()
    assert store.get_openai_api_key() is None


@pytest.mark.parametrize("value", ["", "x\ny", "x\ry", "x" * 4_097])
def test_keyring_store_rejects_invalid_credentials(value: str) -> None:
    store = SystemCredentialStore(FakeKeyring())

    with pytest.raises(ValueError, match="outside supported limits"):
        store.set_openai_api_key(value)


def test_system_keyring_failure_is_safe_and_does_not_fall_back_to_file() -> None:
    class BrokenKeyring:
        def get_password(self, service_name: str, username: str) -> str | None:
            _ = service_name, username
            raise OSError("must not expose this detail")

        def set_password(self, service_name: str, username: str, password: str) -> None:
            _ = service_name, username, password
            raise OSError("must not expose this detail")

        def delete_password(self, service_name: str, username: str) -> None:
            _ = service_name, username
            raise OSError("must not expose this detail")

    store = SystemCredentialStore(BrokenKeyring())

    with pytest.raises(CredentialStoreError) as error:
        store.set_openai_api_key("secret-value")
    assert "must not expose" not in str(error.value)


def test_environment_credential_precedes_keyring(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "environment-secret")

    assert configured_openai_api_key() == "environment-secret"
