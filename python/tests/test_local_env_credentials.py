"""The explicit local launcher reads credentials as data, never shell code."""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from browser_agent.credentials import CredentialStoreError, load_local_env_credentials


def env_file(tmp_path: Path, content: str) -> Path:
    path = tmp_path / ".env"
    path.write_text(content, encoding="utf-8")
    path.chmod(0o600)
    return path


@pytest.fixture(autouse=True)
def empty_credentials(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("BROWSKI_OPENAI_API_KEY", raising=False)
    yield
    os.environ.pop("OPENAI_API_KEY", None)
    os.environ.pop("BROWSKI_OPENAI_API_KEY", None)


def test_loads_only_credential_names_without_shell_evaluation(tmp_path: Path) -> None:
    path = env_file(
        tmp_path,
        'OPENAI_API_KEY="synthetic-$(id)"\nIGNORED_SETTINGS=secret\n',
    )
    load_local_env_credentials(path)
    assert os.environ["OPENAI_API_KEY"] == "synthetic-$(id)"
    assert "IGNORED_SETTINGS" not in os.environ


def test_existing_environment_key_takes_precedence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BROWSKI_OPENAI_API_KEY", "synthetic-environment-key")
    path = env_file(tmp_path, "OPENAI_API_KEY=synthetic-file-key\n")
    load_local_env_credentials(path)
    assert "OPENAI_API_KEY" not in os.environ


def test_rejects_world_readable_credential_file(tmp_path: Path) -> None:
    path = env_file(tmp_path, "OPENAI_API_KEY=synthetic-key\n")
    path.chmod(0o644)
    with pytest.raises(CredentialStoreError, match="owner-only"):
        load_local_env_credentials(path)
    assert "OPENAI_API_KEY" not in os.environ


def test_rejects_symlink_credential_file(tmp_path: Path) -> None:
    path = env_file(tmp_path, "OPENAI_API_KEY=synthetic-key\n")
    link = tmp_path / "alias.env"
    link.symlink_to(path)
    with pytest.raises(OSError):
        load_local_env_credentials(link)


def test_missing_file_is_optional(tmp_path: Path) -> None:
    load_local_env_credentials(tmp_path / "missing.env")
    assert "OPENAI_API_KEY" not in os.environ
