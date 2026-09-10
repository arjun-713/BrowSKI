"""Provider interface: the domain API the agent runtime programs against."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ChatMessage:
    role: str  # "system" | "user" | "assistant" | "tool"
    content: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    tool_call_id: str | None = None


@dataclass
class ProviderCapabilities:
    multimodal: bool = False
    tool_calling: bool = False
    structured_output: bool = False
    max_context_tokens: int | None = None


@dataclass
class ProviderResponse:
    content: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None
    raw: Any | None = None


class Provider(ABC):
    """Replaceable model backend. The browser core never sees this type."""

    name: str = "base"

    @property
    @abstractmethod
    def capabilities(self) -> ProviderCapabilities:
        raise NotImplementedError

    @abstractmethod
    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> ProviderResponse:
        raise NotImplementedError
