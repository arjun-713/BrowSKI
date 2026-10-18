"""Credentials and user-editable runtime settings for the extension bridge."""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from typing import cast

from browser_agent.cli.config import (
    ConfigError,
    RuntimeSettings,
    load_runtime_settings,
    update_runtime_settings,
)
from browser_agent.credentials import CredentialStore
from browser_agent.extension.protocol import PROTOCOL_VERSION

logger = logging.getLogger(__name__)

FrameWriter = Callable[[asyncio.StreamWriter, dict[str, object]], Awaitable[None]]


class ExtensionSettingsService:
    """Handle extension credential and runtime-setting messages.

    Frame output and the credential store are injected so this module owns the
    response behavior without owning Native Messaging transport or the socket.
    """

    def __init__(
        self,
        *,
        config_path: Path | None,
        credential_store: CredentialStore,
        write_frame: FrameWriter,
    ) -> None:
        self._config_path = config_path
        self._credential_store = credential_store
        self._write_frame = write_frame

    async def handle_message(
        self,
        writer: asyncio.StreamWriter,
        message_type: str,
        payload_value: object,
        *,
        active_task: bool,
    ) -> bool:
        """Handle a validated settings/credential message; return if handled."""
        if message_type == "runtime.credentials.set":
            payload = cast(dict[str, object], payload_value)
            api_key = cast(str, payload["apiKey"])
            try:
                self._credential_store.set_openai_api_key(api_key)
                await self.send_credentials_status(writer)
            except Exception:
                logger.warning("BROWSKI could not save an OpenAI key in the system keyring")
                await self.send_credentials_status(
                    writer,
                    error="The operating system credential store is unavailable.",
                )
            return True

        if message_type == "runtime.credentials.clear":
            try:
                self._credential_store.delete_openai_api_key()
                await self.send_credentials_status(writer)
            except Exception:
                logger.warning("BROWSKI could not remove an OpenAI key from the system keyring")
                await self.send_credentials_status(
                    writer,
                    error="The operating system credential store is unavailable.",
                )
            return True

        if message_type == "runtime.credentials.status.request":
            await self.send_credentials_status(writer)
            return True

        if message_type == "runtime.settings.get":
            await self.send_runtime_settings_status(writer)
            return True

        if message_type == "runtime.settings.update":
            if active_task:
                await self.send_runtime_settings_status(
                    writer,
                    error="Runtime settings cannot be changed while a task is active.",
                )
                return True
            payload = cast(Mapping[str, object], payload_value)
            try:
                settings = update_runtime_settings(payload, self._config_path)
            except ConfigError as exc:
                logger.info("Runtime settings update was rejected: %s", exc)
                await self.send_runtime_settings_status(writer, error=str(exc))
            else:
                await self.send_runtime_settings_payload(writer, settings)
            return True

        return False

    async def send_credentials_status(
        self,
        writer: asyncio.StreamWriter,
        *,
        error: str | None = None,
    ) -> None:
        configured = False
        try:
            configured = bool(
                os.environ.get("OPENAI_API_KEY")
                or os.environ.get("BROWSKI_OPENAI_API_KEY")
                or self._credential_store.get_openai_api_key()
            )
        except Exception:
            configured = False

        payload: dict[str, object] = {"openAiKeyConfigured": configured}
        if error is not None:
            payload["error"] = error
        await self._send_status(writer, "runtime.credentials.status", payload)

    async def send_runtime_settings_status(
        self,
        writer: asyncio.StreamWriter,
        *,
        error: str | None = None,
    ) -> None:
        if error is not None:
            await self.send_runtime_settings_payload(writer, None, error=error)
            return

        try:
            settings = load_runtime_settings(self._config_path)
        except ConfigError as exc:
            logger.info("Runtime settings could not be loaded: %s", exc)
            await self.send_runtime_settings_payload(writer, None, error=str(exc))
            return

        await self.send_runtime_settings_payload(writer, settings)

    async def send_runtime_settings_payload(
        self,
        writer: asyncio.StreamWriter,
        settings: RuntimeSettings | None,
        *,
        error: str | None = None,
    ) -> None:
        payload: dict[str, object] = {}
        if settings is not None:
            payload.update(
                {
                    "effort": settings.effort.value,
                    "privacyMode": settings.privacy_mode.value,
                    "layaMode": settings.laya_mode.value,
                    "traceLevel": settings.trace_level.value,
                    "confirmHighRiskActions": settings.confirm_high_risk_actions,
                    "extensionTransport": settings.extension_transport.value,
                    "engine": settings.engine.value,
                    "fastProvider": settings.fast_provider.value,
                    "textProvider": settings.text_provider.value,
                    "allowPaidApi": settings.allow_paid_api,
                    "textModel": settings.text_model,
                    "layaCheckpoint": settings.laya_checkpoint,
                    "jevEndpoint": settings.jev_endpoint,
                }
            )
        if error is not None:
            payload["error"] = error[:200]
        await self._send_status(writer, "runtime.settings.status", payload)

    async def _send_status(
        self,
        writer: asyncio.StreamWriter,
        message_type: str,
        payload: dict[str, object],
    ) -> None:
        await self._write_frame(
            writer,
            {
                "protocolVersion": PROTOCOL_VERSION,
                "type": message_type,
                "eventId": str(uuid.uuid4()),
                "payload": payload,
            },
        )
