"""LiteLLM adapter behind OUR provider interface (optional dependency).

Install with ``pip install "browser-agent[llm]"``. Importing this module
without ``litellm`` installed raises a helpful error instead of breaking the
base package import.
"""

from __future__ import annotations

from typing import Any

from browser_agent.providers.base import (
    ChatMessage,
    Provider,
    ProviderCapabilities,
    ProviderResponse,
)


class LiteLLMProvider(Provider):
    """Generic LiteLLM-backed provider (any LiteLLM-supported model)."""

    name = "litellm"

    def __init__(self, model: str, **kwargs: Any) -> None:
        self.model = model
        self._kwargs = kwargs

    @property
    def capabilities(self) -> ProviderCapabilities:
        # Conservative defaults; refined per-model in Milestone 8.
        return ProviderCapabilities(multimodal=False, tool_calling=True, structured_output=False)

    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> ProviderResponse:
        try:
            import litellm  # type: ignore[import-not-found]
        except ImportError as e:  # pragma: no cover
            raise RuntimeError(
                'LiteLLMProvider requires the "llm" extra: pip install "browser-agent[llm]"'
            ) from e
        import asyncio

        payload = [{"role": m.role, "content": m.content} for m in messages]
        kwargs = dict(self._kwargs)

        def _call() -> Any:
            # getattr: litellm's re-exported symbols are loosely typed;
            # resolve dynamically and treat the boundary as Any.
            completion: Any = getattr(litellm, "completion")  # noqa: B009 - keeps pyright strict green; litellm re-export is loosely typed
            return completion(
                model=self.model,
                messages=payload,
                **kwargs,
            )

        response: Any = await asyncio.to_thread(_call)
        message: Any = response["choices"][0]["message"]
        usage: Any = response.get("usage", {}) or {}
        return ProviderResponse(
            content=str(message.get("content") or ""),
            tool_calls=list(message.get("tool_calls") or []),
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
            raw=response,
        )
