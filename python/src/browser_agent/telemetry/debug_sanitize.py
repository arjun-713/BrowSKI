"""Best-effort sanitization for opt-in local debug records."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import cast
from urllib.parse import urlsplit, urlunsplit

_REDACTED = "[REDACTED]"
_OMITTED = "[OMITTED]"
_MAX_DEPTH = 12
_MAX_ITEMS = 20_000
_MAX_STRING_LENGTH = 4_096
_PRIVATE_FIELDS = frozenset(
    {
        "authorization",
        "headers",
        "environment",
        "env",
        "api_key",
        "password",
        "cookie",
        "cookies",
        "token",
        "access_token",
        "refresh_token",
        "client_secret",
        "private_key",
        "encrypted_content",
        "reasoning",
        "logprobs",
        "value",
        "script",
        "screenshot",
        "image",
        "image_data",
        "base64",
    }
)
_NORMALIZED_PRIVATE_FIELDS = frozenset(re.sub(r"[^a-z0-9]", "", field) for field in _PRIVATE_FIELDS)
_URL_PATTERN = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_CREDENTIAL_ASSIGNMENT = re.compile(
    r"(?i)(\b(?:password|passphrase|passcode|pin|credential|secret|"
    r"client[_ -]*secret|private[_ -]*key|authorization|bearer|cookie|"
    r"api[_ -]*key|access[_ -]*token|refresh[_ -]*token|token)\b"
    r"\s*[:=]\s*)((?:bearer\s+)?\"[^\"]*\"|(?:bearer\s+)?'[^']*'|"
    r"bearer\s+[^\s,;&]+|[^\s,;&]+)"
)
_BASE64_LIKE = re.compile(r"^[A-Za-z0-9+/]{256,}={0,2}$")


def has_recognized_sensitive_label(value: str) -> bool:
    # Provider packages also use debug capture. Load their recognizers only
    # while writing a record, after module initialization has completed.
    from browser_agent.providers.privacy import has_recognized_sensitive_label as recognize

    return recognize(value)


def has_recognized_sensitive_content(value: str) -> bool:
    from browser_agent.providers.privacy import has_recognized_sensitive_content as recognize

    return recognize(value)


def sanitize_debug_payload(payload: Mapping[str, object]) -> dict[str, object]:
    """Return a JSON-safe copy with sensitive values redacted or omitted."""
    state = [0]
    sanitized = _sanitize_value(payload, "", 0, state)
    if isinstance(sanitized, dict):
        return cast(dict[str, object], sanitized)
    return {"payload": sanitized}


def _sanitize_value(
    value: object,
    key: str,
    depth: int,
    state: list[int],
    *,
    credential_element: bool = False,
) -> object:
    state[0] += 1
    if state[0] > _MAX_ITEMS or depth >= _MAX_DEPTH:
        return _OMITTED

    normalized_key = re.sub(r"[^a-z0-9]", "", key.casefold())
    if normalized_key in _NORMALIZED_PRIVATE_FIELDS or has_recognized_sensitive_label(key):
        return _REDACTED

    if isinstance(value, Mapping):
        object_values = cast(Mapping[object, object], value)
        sensitive = _is_credential_element(object_values)
        sanitized: dict[str, object] = {}
        for index, (child_key, child_value) in enumerate(object_values.items()):
            if index >= _MAX_ITEMS:
                sanitized["[truncated]"] = _OMITTED
                break
            if not isinstance(child_key, str):
                continue
            if _is_always_omitted_key(child_key):
                continue
            sanitized[child_key[:128]] = _sanitize_value(
                child_value,
                child_key,
                depth + 1,
                state,
                credential_element=sensitive and child_key.casefold() in {"value", "text"},
            )
        return sanitized

    if isinstance(value, (list, tuple)):
        sequence = cast(list[object] | tuple[object, ...], value)
        sanitized_items: list[object] = []
        for item in sequence[:_MAX_ITEMS]:
            sanitized_items.append(_sanitize_value(item, key, depth + 1, state))
        if len(sequence) > _MAX_ITEMS:
            sanitized_items.append(_OMITTED)
        return sanitized_items

    if isinstance(value, str):
        if credential_element:
            return _REDACTED
        if _looks_base64(value):
            return _OMITTED
        return _sanitize_text(value)

    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _OMITTED


def _is_credential_element(values: Mapping[object, object]) -> bool:
    for field in ("role", "semantic_kind", "input_type"):
        value = values.get(field)
        if isinstance(value, str) and has_recognized_sensitive_label(value):
            return True
    for field in ("name", "accessible_name", "label", "placeholder", "key", "target_ref", "ref"):
        value = values.get(field)
        if isinstance(value, str) and has_recognized_sensitive_label(value):
            return True
    return False


def _is_always_omitted_key(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", key.casefold())
    return normalized in {"headers", "environment", "env", "base64"} or any(
        token in normalized for token in ("screenshot", "image")
    )


def _sanitize_text(value: str) -> str:
    if len(value) > _MAX_STRING_LENGTH:
        value = value[:_MAX_STRING_LENGTH] + "…[truncated]"
    if has_recognized_sensitive_content(value):
        return _REDACTED
    value = _CREDENTIAL_ASSIGNMENT.sub(r"\1[REDACTED]", value)
    return _URL_PATTERN.sub(_sanitize_url, value)


def _sanitize_url(match: re.Match[str]) -> str:
    raw_url = match.group(0).rstrip(".,);]")
    suffix = match.group(0)[len(raw_url) :]
    try:
        parts = urlsplit(raw_url)
        host = parts.hostname or ""
        if parts.port is not None:
            host = f"{host}:{parts.port}"
        safe_url = urlunsplit((parts.scheme, host, parts.path, "", ""))
        return safe_url + suffix
    except ValueError:
        return "[URL REDACTED]" + suffix


def _looks_base64(value: str) -> bool:
    if len(value) < 256:
        return False
    sample = value[:_MAX_STRING_LENGTH]
    return _BASE64_LIKE.fullmatch(sample) is not None
