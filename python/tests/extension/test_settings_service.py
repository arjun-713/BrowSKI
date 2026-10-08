"""Tests for extension-local settings and credential response handling."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import cast

import pytest

from browser_agent.credentials import CredentialStore
from browser_agent.extension.settings_service import ExtensionSettingsService


class FakeCredentialStore:
    def __init__(self) -> None:
        self.api_key: str | None = None
        self.failure: Exception | None = None

    def get_openai_api_key(self) -> str | None:
        if self.failure is not None:
            raise self.failure
        return self.api_key

    def set_openai_api_key(self, api_key: str) -> None:
        if self.failure is not None:
            raise self.failure
        self.api_key = api_key

    def delete_openai_api_key(self) -> None:
        if self.failure is not None:
            raise self.failure
        self.api_key = None


def _service(
    tmp_path: Path,
    captured: list[dict[str, object]],
    store: FakeCredentialStore | None = None,
) -> ExtensionSettingsService:
    async def write_frame(_writer: asyncio.StreamWriter, message: dict[str, object]) -> None:
        captured.append(message)

    config_path = tmp_path / "config.toml"
    config_path.write_text(
        (Path(__file__).parents[2] / "src/browser_agent/cli/default.toml").read_text(
            encoding="utf-8"
        ),
        encoding="utf-8",
    )
    return ExtensionSettingsService(
        config_path=config_path,
        credential_store=cast(CredentialStore, store or FakeCredentialStore()),
        write_frame=write_frame,
    )


def _writer() -> asyncio.StreamWriter:
    return cast(asyncio.StreamWriter, object())


@pytest.mark.asyncio
async def test_credential_messages_only_report_configuration_state(
    tmp_path: Path,
) -> None:
    captured: list[dict[str, object]] = []
    store = FakeCredentialStore()
    service = _service(tmp_path, captured, store)

    handled = await service.handle_message(
        _writer(),
        "runtime.credentials.set",
        {"apiKey": "sk-test-secret"},
        active_task=False,
    )

    assert handled is True
    assert store.api_key == "sk-test-secret"
    assert captured[-1]["type"] == "runtime.credentials.status"
    assert captured[-1]["payload"] == {"openAiKeyConfigured": True}
    assert "sk-test-secret" not in repr(captured)


@pytest.mark.asyncio
async def test_credential_store_failure_has_generic_secret_free_status(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    captured: list[dict[str, object]] = []
    store = FakeCredentialStore()
    store.failure = RuntimeError("store failure included sk-never-log")
    service = _service(tmp_path, captured, store)

    await service.handle_message(
        _writer(),
        "runtime.credentials.set",
        {"apiKey": "sk-never-echo"},
        active_task=False,
    )

    assert captured[-1]["type"] == "runtime.credentials.status"
    assert captured[-1]["payload"] == {
        "openAiKeyConfigured": False,
        "error": "The operating system credential store is unavailable.",
    }
    assert "sk-never" not in repr(captured)
    assert "sk-never" not in caplog.text


@pytest.mark.asyncio
async def test_runtime_settings_read_and_active_task_refusal_are_exact(
    tmp_path: Path,
) -> None:
    captured: list[dict[str, object]] = []
    service = _service(tmp_path, captured)
    config_path = tmp_path / "config.toml"
    config_before = config_path.read_text(encoding="utf-8")

    await service.handle_message(_writer(), "runtime.settings.get", {}, active_task=False)
    settings_frame = captured[-1]
    settings_payload = cast(dict[str, object], settings_frame["payload"])
    assert settings_frame["type"] == "runtime.settings.status"
    assert settings_payload["effort"] == "low"
    assert settings_payload["confirmHighRiskActions"] is True

    await service.handle_message(
        _writer(),
        "runtime.settings.update",
        {
            "effort": "none",
            "privacyMode": "offline",
            "layaMode": "disabled",
            "traceLevel": "detailed",
        },
        active_task=True,
    )
    assert captured[-1]["payload"] == {
        "error": "Runtime settings cannot be changed while a task is active."
    }
    assert config_path.read_text(encoding="utf-8") == config_before


@pytest.mark.asyncio
async def test_runtime_settings_errors_are_bounded(
    tmp_path: Path,
) -> None:
    captured: list[dict[str, object]] = []
    service = _service(tmp_path, captured)

    await service.send_runtime_settings_payload(_writer(), None, error="x" * 250)

    payload = cast(dict[str, object], captured[-1]["payload"])
    assert set(payload) == {"error"}
    assert len(cast(str, payload["error"])) == 200
