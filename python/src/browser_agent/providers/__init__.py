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
from browser_agent.providers.privacy import (
    LocalTokenVault,
    OutboundProvider,
    PrivacyMode,
    ProviderBoundary,
    ProviderBoundaryError,
    VisionProviderBoundary,
)

__all__ = [
    "ChatMessage",
    "LocalTokenVault",
    "OutboundProvider",
    "PrivacyMode",
    "Provider",
    "ProviderBoundary",
    "ProviderBoundaryError",
    "VisionProviderBoundary",
    "ProviderCapabilities",
    "ProviderResponse",
    "describe",
]
