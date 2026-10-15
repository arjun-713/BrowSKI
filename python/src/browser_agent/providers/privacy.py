"""Provider payload inspection and optional local privacy-first tokenization."""

from __future__ import annotations

import inspect
import re
from enum import StrEnum
from typing import Any, cast

from pydantic import BaseModel

from browser_agent.reasoning.contracts import (
    ReasoningAction,
    ReasoningContext,
    ReasoningDecision,
    ReasoningEffort,
    ReasoningProvider,
)
from browser_agent.vision.contracts import VisionInterpretation, VisionProvider, VisionRequest


class PrivacyMode(StrEnum):
    STANDARD = "standard"
    PRIVACY_FIRST = "privacy_first"
    OFFLINE = "offline"


class ProviderBoundaryError(RuntimeError):
    """Raised when policy does not permit an outbound provider request."""


class OutboundProvider(BaseModel):
    provider: str
    operation: str
    context_characters: int
    redacted_values: int


_PII_PATTERNS = (
    re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b"),
    re.compile(r"(?<!\w)(?:\+?\d[\d .()/-]{7,}\d)(?!\w)"),
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    re.compile(r"\b(?:\d[ -]*?){13,19}\b"),
)
_SECRET_PATTERN = re.compile(
    r"(?i)\b(?:sk[-_](?:live|test)[-_][A-Za-z0-9_-]{12,}|sk-[A-Za-z0-9_-]{12,}|"
    r"gh[pousr]_[A-Za-z0-9_]{20,}|AKIA[A-Z0-9]{16}|"
    r"xox[baprs]-[A-Za-z0-9-]{10,}|AIza[0-9A-Za-z_-]{30,}|"
    r"glpat-[A-Za-z0-9_-]{20,}|npm_[A-Za-z0-9]{20,}|"
    r"hf_[A-Za-z0-9]{20,}|eyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\."
    r"[A-Za-z0-9_-]{5,})\b"
)
_CREDENTIAL_ROLES = frozenset({"password", "passwordbox", "credential"})
_PRIVATE_KEYS = frozenset(
    {
        "access_token",
        "api_key",
        "auth_token",
        "authorization",
        "authorization_header",
        "bearer_token",
        "cookie",
        "credit_card",
        "credential",
        "csrf_token",
        "cvv",
        "cvc",
        "id_token",
        "mfa_code",
        "one_time_code",
        "otp",
        "passcode",
        "password",
        "passphrase",
        "pin",
        "private_key",
        "refresh_token",
        "secret",
        "secret_key",
        "session_token",
        "session_id",
        "social_security_number",
        "ssn",
        "token",
        "token_value",
        "client_secret",
        "set_cookie",
    }
)
_PRIVATE_KEY_NAMES = frozenset(re.sub(r"[^a-z0-9]", "", key) for key in _PRIVATE_KEYS)
_SENSITIVE_LABEL_PATTERN = re.compile(
    r"(?i)\b(?:password|passphrase|passcode|pin|credential|secret|"
    r"client[\s_-]*secret|private[\s_-]*key|secret[\s_-]*key|"
    r"auth(?:entication|orization)?|bearer|cookie|session|csrf|"
    r"api[\s_-]*key|access[\s_-]*token|refresh[\s_-]*token|"
    r"id[\s_-]*token|one[\s_-]*time(?:[\s_-]*code)?|mfa[\s_-]*code|otp|"
    r"security[\s_-]*code|verification[\s_-]*code|recovery[\s_-]*code|"
    r"credit[\s_-]*card|cvv|cvc|medical|health|diagnos(?:is|tic)?|"
    r"patient|treatment|symptom|medication|prescription)\b"
)


def has_recognized_sensitive_label(label: str) -> bool:
    """Best-effort check for common private-data labels, not universal detection."""
    return _SENSITIVE_LABEL_PATTERN.search(label) is not None


def has_recognized_sensitive_content(value: str) -> bool:
    """Best-effort check for supported token and PII patterns."""
    if _SECRET_PATTERN.search(value) is not None:
        return True
    return any(pattern.search(value) is not None for pattern in _PII_PATTERNS)


def _normalized_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]", "", key.casefold())


class LocalTokenVault:
    """Keep token-to-value mappings transiently for one provider request."""

    def __init__(self) -> None:
        self._values: dict[str, str] = {}

    def tokenize(self, value: str) -> str:
        for token, original in self._values.items():
            if value == original:
                return token
        token = f"<PRIVATE_{len(self._values) + 1}>"
        self._values[token] = value
        return token

    def restore(self, value: str) -> str:
        return self._values.get(value, value)

    def restore_text(self, value: str) -> str:
        """Restore only vault tokens embedded in a local typed action value."""
        for token, original in self._values.items():
            value = value.replace(token, original)
        return value

    def clear(self) -> None:
        self._values.clear()

    @property
    def value_count(self) -> int:
        return len(self._values)


class ProviderBoundary:
    """Central reasoning-provider boundary with explicit privacy policy."""

    async def aclose(self) -> None:
        """Delegate resource cleanup without exporting private context."""
        close = getattr(self._provider, "aclose", None)
        if callable(close):
            close_result = close()
            if not inspect.isawaitable(close_result):
                raise TypeError("reasoning provider aclose() must return an awaitable")
            await close_result

    def __init__(
        self,
        provider: ReasoningProvider,
        *,
        mode: PrivacyMode = PrivacyMode.STANDARD,
        max_context_characters: int = 32_000,
    ) -> None:
        if max_context_characters <= 0:
            raise ValueError("max_context_characters must be positive")
        self._provider = provider
        self._mode = mode
        self._max_context_characters = max_context_characters

    async def reason(
        self,
        context: ReasoningContext,
        *,
        model: str,
        effort: ReasoningEffort,
    ) -> ReasoningDecision:
        """Apply mode policy before forwarding the typed context."""
        if self._mode == PrivacyMode.OFFLINE:
            raise ProviderBoundaryError("Privacy mode offline blocks remote providers")

        vault = LocalTokenVault()
        try:
            self.inspect(context)
            safe_context = (
                self._sanitize_context(context, vault)
                if self._mode == PrivacyMode.PRIVACY_FIRST
                else context
            )
            decision = await self._provider.reason(safe_context, model=model, effort=effort)
            if self._mode != PrivacyMode.PRIVACY_FIRST:
                return decision
            return self._restore_decision(decision, vault)
        finally:
            vault.clear()

    def _restore_decision(
        self,
        decision: ReasoningDecision,
        vault: LocalTokenVault,
    ) -> ReasoningDecision:
        payload = cast(dict[str, object], decision.model_dump(mode="python"))
        action = decision.action
        if action is not None:
            payload["action"] = self._restore_action(action, vault)
        payload["candidate_actions"] = [
            self._restore_action(candidate, vault) for candidate in decision.candidate_actions
        ]
        return ReasoningDecision.model_validate(payload)

    def _restore_action(self, action: ReasoningAction, vault: LocalTokenVault) -> ReasoningAction:
        payload = cast(dict[str, object], action.model_dump(mode="python"))
        for field_name in ("text", "value"):
            value = payload.get(field_name)
            if isinstance(value, str):
                payload[field_name] = vault.restore_text(value)
        return ReasoningAction.model_validate(payload)

    def inspect(self, context: ReasoningContext) -> OutboundProvider:
        """Return safe metadata only; never retain or log the payload."""
        serialized = context.model_dump_json(exclude_none=True)
        if len(serialized) > self._max_context_characters:
            raise ProviderBoundaryError("Outbound provider context exceeds configured limit")
        count = 0
        if self._mode == PrivacyMode.PRIVACY_FIRST:
            count = self._count_sensitive_values(context.model_dump(mode="json"))
        return OutboundProvider(
            provider="openai",
            operation="reason",
            context_characters=len(serialized),
            redacted_values=count,
        )

    def _sanitize_context(
        self,
        context: ReasoningContext,
        vault: LocalTokenVault,
    ) -> ReasoningContext:
        payload = cast(
            dict[str, object],
            context.model_dump(mode="json", exclude_none=False),
        )
        sanitized = self._sanitize_value(payload, vault)
        return ReasoningContext.model_validate(sanitized)

    def _sanitize_value(
        self,
        value: object,
        vault: LocalTokenVault,
        key: str = "",
    ) -> object:
        if isinstance(value, dict):
            object_values = cast(dict[str, object], value)
            role = _normalized_key(str(object_values.get("role", "")))
            semantic_kind = _normalized_key(str(object_values.get("semantic_kind", "")))
            label_fields = (
                "name",
                "accessible_name",
                "label",
                "placeholder",
                "input_type",
                "source_label",
                "destination_label",
            )
            labels: list[str] = []
            for field_name in label_fields:
                label = object_values.get(field_name)
                if isinstance(label, str):
                    labels.append(label)
            record_key = object_values.get("key")
            if "value" in object_values and isinstance(record_key, str):
                labels.append(record_key)
            has_sensitive_label = any(
                _SENSITIVE_LABEL_PATTERN.search(label) is not None for label in labels
            )
            sensitive_element = (
                role in _CREDENTIAL_ROLES
                or semantic_kind in _CREDENTIAL_ROLES
                or has_sensitive_label
            )
            if sensitive_element:
                for field_name in ("value", "text"):
                    field_value = object_values.get(field_name)
                    if isinstance(field_value, str):
                        object_values[field_name] = vault.tokenize(field_value)
            return {
                child_key: self._sanitize_value(
                    child_value,
                    vault,
                    child_key.casefold(),
                )
                for child_key, child_value in object_values.items()
            }
        if isinstance(value, list):
            items = cast(list[object], value)
            return [self._sanitize_value(item, vault, key) for item in items]
        if isinstance(value, str):
            if _normalized_key(key) in _PRIVATE_KEY_NAMES:
                return vault.tokenize(value)
            return self._sanitize_text(value, vault)
        return value

    def _sanitize_text(self, value: str, vault: LocalTokenVault) -> str:
        sanitized = _SECRET_PATTERN.sub(lambda match: vault.tokenize(match.group()), value)
        for pattern in _PII_PATTERNS:
            sanitized = pattern.sub(lambda match: vault.tokenize(match.group()), sanitized)
        return sanitized

    def _count_sensitive_values(self, value: Any) -> int:
        vault = LocalTokenVault()
        try:
            self._sanitize_value(value, vault)
            return vault.value_count
        finally:
            vault.clear()


class VisionProviderBoundary:
    """Fail-closed outbound boundary for transient screenshot requests.

    Screenshot redaction is not implemented yet, so images may leave the
    process only in standard mode. Privacy-first and offline modes block them.
    """

    def __init__(
        self,
        provider: VisionProvider,
        *,
        mode: PrivacyMode = PrivacyMode.STANDARD,
        max_context_characters: int = 32_000,
    ) -> None:
        if max_context_characters <= 0:
            raise ValueError("max_context_characters must be positive")
        self._provider = provider
        self._mode = mode
        self._max_context_characters = max_context_characters

    async def interpret(self, request: VisionRequest) -> VisionInterpretation:
        if self._mode != PrivacyMode.STANDARD:
            raise ProviderBoundaryError(
                "Vision provider is blocked until screenshot redaction is available"
            )
        safe_metadata = request.model_dump_json(exclude={"screenshot"})
        if len(safe_metadata) > self._max_context_characters:
            raise ProviderBoundaryError("Outbound vision context exceeds configured limit")
        return await self._provider.interpret(request)
