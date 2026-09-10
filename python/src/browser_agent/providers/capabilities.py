"""Capability detection helpers for providers."""

from __future__ import annotations

from browser_agent.providers.base import ProviderCapabilities


def describe(cap: ProviderCapabilities) -> str:
    parts = [
        f"multimodal={cap.multimodal}",
        f"tool_calling={cap.tool_calling}",
        f"structured_output={cap.structured_output}",
    ]
    if cap.max_context_tokens is not None:
        parts.append(f"max_context_tokens={cap.max_context_tokens}")
    return ", ".join(parts)
