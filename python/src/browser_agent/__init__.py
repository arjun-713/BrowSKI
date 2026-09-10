"""browser-agent: general-purpose open-source browser agent (scaffold, v0.1).

Slice status: :class:`BrowserSession` (launch / navigate / observe / close)
works against a live Chromium driven by the Rust core. Autonomous planning,
memory, recovery, and provider orchestration are contracts/interfaces only.
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
