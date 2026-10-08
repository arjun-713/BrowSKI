"""BROWSKI browser runtime and agent orchestration package.

The Rust core owns Chromium observation and action execution. The Python graph
orchestrates typed decisions, bounded memory and recovery, provider policy,
and the local product service. The browser extension remains a UI and bridge.
"""

from browser_agent._types import (
    ActionResult,
    AgentDecision,
    AgentObservation,
    BrowserAction,
    DialogSummary,
    ElementChange,
    ElementRef,
    FailureKind,
    FormSummary,
    PrunedElement,
    RecoveryDecision,
    SemanticElement,
    SemanticKind,
    SemanticSnapshot,
    SnapshotDelta,
    TabInfo,
    TaskState,
    TextBlock,
    TraceEvent,
    VerificationResult,
    Viewport,
    VisibilityClass,
    WorkingMemory,
)
from browser_agent.session import BrowserSession

__all__ = [
    "ActionResult",
    "AgentDecision",
    "AgentObservation",
    "BrowserAction",
    "BrowserSession",
    "DialogSummary",
    "ElementChange",
    "ElementRef",
    "FailureKind",
    "FormSummary",
    "PrunedElement",
    "RecoveryDecision",
    "SemanticElement",
    "SemanticKind",
    "SemanticSnapshot",
    "SnapshotDelta",
    "TabInfo",
    "TaskState",
    "TextBlock",
    "TraceEvent",
    "VerificationResult",
    "Viewport",
    "VisibilityClass",
    "WorkingMemory",
    "__version__",
]

__version__ = "0.1.0"
