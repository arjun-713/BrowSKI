"""Extract public response data without hidden reasoning or transport secrets."""

from __future__ import annotations

import json
import re
from typing import cast

from pydantic import BaseModel


def public_response_payload(response: object) -> dict[str, object]:
    """Retain message output and usage; omit reasoning items and encrypted content."""
    payload: dict[str, object] = {}
    for name in ("id", "model", "status"):
        value: object = getattr(response, name, None)
        if isinstance(value, str):
            payload[name] = value
    usage: object = getattr(response, "usage", None)
    payload["usage"] = {
        name: getattr(usage, name, None)
        for name in ("input_tokens", "output_tokens", "total_tokens")
    }
    parsed: object = getattr(response, "output_parsed", None)
    if isinstance(parsed, BaseModel):
        payload["output_parsed"] = parsed.model_dump(mode="json")
    elif isinstance(parsed, dict):
        payload["output_parsed"] = cast(dict[str, object], parsed)

    messages: list[dict[str, object]] = []
    output: object = getattr(response, "output", None)
    if isinstance(output, list):
        for item in cast(list[object], output):
            if getattr(item, "type", None) != "message":
                continue
            content: object = getattr(item, "content", None)
            if not isinstance(content, list):
                continue
            for part in cast(list[object], content):
                text: object = getattr(part, "text", None)
                if getattr(part, "type", None) == "output_text" and isinstance(text, str):
                    try:
                        value: object = json.loads(text)
                    except json.JSONDecodeError:
                        value = text
                    messages.append({"type": "output_text", "content": value})
    payload["output"] = messages
    return payload


def public_error_payload(error: Exception) -> dict[str, object]:
    """Report safe request classifications; SDK error messages can echo prompts."""
    payload: dict[str, object] = {"error_type": type(error).__name__}
    status: object = getattr(error, "status_code", None)
    if type(status) is int:
        payload["http_status"] = status
    body: object = getattr(error, "body", None)
    if isinstance(body, dict):
        fields = cast(dict[str, object], body)
        details: object = fields.get("error", fields)
        if isinstance(details, dict):
            code = cast(dict[str, object], details).get("code")
            if isinstance(code, str) and re.fullmatch(r"[a-z_]{1,64}", code):
                payload["error_code"] = code
    return payload
