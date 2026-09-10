"""Provider abstraction: OUR interface first, LiteLLM only as an adapter.

Rule: do not let LiteLLM become the domain API. The agent runtime depends on
:class:`Provider` / :class:`ChatMessage` / :class:`ProviderCapabilities`;
``litellm_adapter`` is one optional backend behind that interface.
"""

from browser_agent.providers.base import (
    ChatMessage,
    Provider,
    ProviderCapabilities,
    ProviderResponse,
)
from browser_agent.providers.capabilities import describe

__all__ = ["ChatMessage", "Provider", "ProviderCapabilities", "ProviderResponse", "describe"]
