"""Shared domain contracts (Python mirror of the Rust models).

Ownership rule: the Rust crates own the browser-side schemas
(`SemanticSnapshot`, element identity, actions, verification). This module
mirrors them in Pydantic v2 for the agent runtime. Any change that alters the
serialized shape must follow ``docs/protocols/versioning.md`` and, when
non-trivial, an ADR.

Keep this file small: minimal domain models now, evolve with measurement.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class ElementRef(BaseModel):
    ref: str = Field(description="Stable semantic ref, e.g. @search_input")
    id: int = Field(default=0, description="Opaque registry identity")
    generation: int = Field(default=0, description="Generation in which the ref was bound")

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.ref


class VisibilityClass(StrEnum):
    VISIBLE = "VISIBLE"
    HIDDEN = "HIDDEN"
    OFFSCREEN = "OFFSCREEN"
    OCCLUDED = "OCCLUDED"


class SemanticKind(StrEnum):
    GENERIC = "generic"
    BUTTON = "button"
    LINK = "link"
    TEXT_INPUT = "text_input"
    OPTION = "option"
    OPTION_LIST = "option_list"
    CHECKABLE = "checkable"
    HEADING = "heading"
    TEXT = "text"
    REGION = "region"
    FORM = "form"
    DIALOG = "dialog"
    ALERT = "alert"
    TABLE = "table"
    NAVIGATION = "navigation"
    IMAGE = "image"


class BBox(BaseModel):
    x: float
    y: float
    width: float
    height: float


class Viewport(BaseModel):
    width: float = 0.0
    height: float = 0.0
    device_scale_factor: float = 0.0


class SemanticElement(BaseModel):
    id: int = 0
    ref: str
    generation: int = 0
    role: str
    accessible_name: str | None = None
    text: str | None = None
    value: str | None = None
    state: list[str] = Field(default_factory=list[str])
    bbox: BBox | None = None
    visible: bool = True
    visibility: VisibilityClass = VisibilityClass.VISIBLE
    enabled: bool = True
    interactable: bool = True
    frame: str | None = None
    frame_path: list[str] = Field(default_factory=list[str])
    semantic_kind: SemanticKind = SemanticKind.GENERIC
    backend_node_id: int | None = None
    doc_order: int = 0
    ancestry: list[str] = Field(default_factory=list[str])
    confidence: float = 1.0
    fingerprint: str


class TextBlock(BaseModel):
    kind: str
    level: int | None = None
    text: str
    frame_path: list[str] = Field(default_factory=list[str])


class FormSummary(BaseModel):
    name: str | None = None
    controls: list[str] = Field(default_factory=list[str])
    submit: str | None = None
    frame_path: list[str] = Field(default_factory=list[str])


class DialogSummary(BaseModel):
    kind: str
    name: str | None = None
    modal: bool = False
    frame_path: list[str] = Field(default_factory=list[str])


class TabInfo(BaseModel):
    id: str
    target: str
    title: str = ""
    url: str = ""
    frames: int = 0
    has_session: bool = False
    crashed: bool = False


class SemanticSnapshot(BaseModel):
    schema_version: int = 1
    url: str
    title: str | None = None
    tabs: list[str] = Field(default_factory=list[str])
    active_tab: str | None = None
    active_frame: str | None = None
    viewport: Viewport = Field(default_factory=Viewport)
    scroll: dict[str, int] = Field(default_factory=lambda: {"x": 0, "y": 0})
    interactive_elements: list[SemanticElement] = Field(default_factory=list[SemanticElement])
    elements: list[SemanticElement] = Field(default_factory=list[SemanticElement])
    text_excerpt: str | None = None
    text_blocks: list[TextBlock] = Field(default_factory=list[TextBlock])
    form_count: int = 0
    forms: list[FormSummary] = Field(default_factory=list[FormSummary])
    dialogs: list[str] = Field(default_factory=list[str])
    dialog_summaries: list[DialogSummary] = Field(default_factory=list[DialogSummary])
    focused: str | None = None
    page_fingerprint: str
    state_generation: int

    def by_ref(self, reference: str) -> SemanticElement | None:
        return next((e for e in self.elements if e.ref == reference), None)


class ElementChange(BaseModel):
    ref: str
    fields: list[str] = Field(default_factory=list[str])


class SnapshotDelta(BaseModel):
    added: list[str] = Field(default_factory=list[str])
    removed: list[str] = Field(default_factory=list[str])
    changed: list[ElementChange] = Field(default_factory=list[ElementChange])
    moved: list[str] = Field(default_factory=list[str])
    navigation_changed: bool = False
    focus_changed: bool = False

    def is_empty(self) -> bool:
        return not (
            self.added
            or self.removed
            or self.changed
            or self.moved
            or self.navigation_changed
            or self.focus_changed
        )


class PrunedElement(BaseModel):
    ref: str
    role: str
    name: str | None = None
    text: str | None = None
    value: str | None = None
    state: list[str] = Field(default_factory=list[str])
    interactable: bool = True


class AgentObservation(BaseModel):
    url: str
    title: str | None = None
    active_tab: str | None = None
    state_generation: int = 0
    page_fingerprint: str = ""
    elements: list[PrunedElement] = Field(default_factory=list[PrunedElement])
    truncated: bool = False
    focused: str | None = None

    def render_text(self) -> str:
        lines: list[str] = []
        for el in self.elements:
            lines.append(el.ref)
            lines.append(f"  {el.role}")
            if el.name:
                lines.append(f'  name="{el.name}"')
            if el.text:
                lines.append(f'  "{el.text}"')
            if el.value:
                lines.append(f'  value="{el.value}"')
            if el.state:
                lines.append(f"  [{', '.join(el.state)}]")
            if not el.interactable:
                lines.append("  (not interactable)")
        if self.truncated:
            lines.append("…(truncated: full state has more elements)")
        return "\n".join(lines) + "\n" if lines else ""


class BrowserAction(BaseModel):
    """Python mirror of Rust's tagged ``BrowserAction`` enum."""

    type: Literal[
        "click",
        "type",
        "select",
        "check",
        "press",
        "scroll",
        "hover",
        "navigate",
        "back",
        "forward",
        "reload",
        "activate_tab",
        "close_tab",
        "new_tab",
        "handle_dialog",
        "wait",
    ]
    target: ElementRef | None = None
    text: str | None = None
    clear: bool = True
    submit: bool = False
    value: str | None = None
    by: Literal["value", "label"] = "value"
    checked: bool | None = None
    key: str | None = None
    dx: int = 0
    dy: int = 0
    url: str | None = None
    tab: str | None = None
    accept: bool | None = None
    ms: int | None = None
    expected_effect: Any | None = None
    options: dict[str, Any] = Field(default_factory=dict[str, Any])

    @model_validator(mode="after")
    def validate_action_fields(self) -> BrowserAction:
        target_required = {"click", "type", "select", "check", "hover"}
        if self.type in target_required and self.target is None:
            raise ValueError(f"{self.type} action requires a semantic target")
        if self.type == "type" and self.text is None:
            raise ValueError("type action requires text")
        if self.type == "select" and self.value is None:
            raise ValueError("select action requires a value")
        if self.type == "check" and self.checked is None:
            raise ValueError("check action requires checked=true or false")
        if self.type == "press" and self.key is None:
            raise ValueError("press action requires a key")
        if self.type in {"activate_tab", "close_tab"} and self.tab is None:
            raise ValueError(f"{self.type} action requires a tab id")
        if self.type == "handle_dialog" and self.accept is None:
            raise ValueError("handle_dialog action requires accept=true or false")
        if self.type == "wait" and self.ms is None:
            raise ValueError("wait action requires milliseconds")
        return self


class ActionResult(BaseModel):
    ok: bool
    action: BrowserAction
    before_generation: int | None = None
    after_generation: int | None = None
    evidence: dict[str, Any] = Field(default_factory=dict[str, Any])


class VerificationStatus(StrEnum):
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    UNCERTAIN = "UNCERTAIN"


class VerificationResult(BaseModel):
    status: VerificationStatus
    expected: str
    observed: str
    evidence: dict[str, Any] = Field(default_factory=dict[str, Any])
    state_delta: dict[str, Any] = Field(default_factory=dict[str, Any])


class FailureKind(StrEnum):
    GROUNDING = "GROUNDING"
    PLANNING = "PLANNING"
    MEMORY = "MEMORY"
    EXECUTION = "EXECUTION"
    VERIFICATION = "VERIFICATION"
    RECOVERY = "RECOVERY"
    VISION = "VISION"
    NAVIGATION = "NAVIGATION"
    FRAME = "FRAME"
    TAB = "TAB"
    UPLOAD = "UPLOAD"
    DOWNLOAD = "DOWNLOAD"
    AUTH = "AUTH"
    TIMEOUT = "TIMEOUT"
    STAGNATION = "STAGNATION"
    SITE_BLOCK = "SITE_BLOCK"
    MODEL_FORMAT = "MODEL_FORMAT"
    SAFETY = "SAFETY"
    UNKNOWN = "UNKNOWN"


class RecoveryDecision(BaseModel):
    decision: Literal["retry", "reacquire_and_retry", "replan", "escalate"]
    attempt: int = 0
    max_attempts: int = 3
    reason: str = ""


class TaskState(BaseModel):
    """Explicit task state for long-running tasks (expanded in M7)."""

    task: str
    goal: str | None = None
    milestones: list[str] = Field(default_factory=list[str])
    completed: list[str] = Field(default_factory=list[str])
    failed_strategies: list[str] = Field(default_factory=list[str])
    steps_taken: int = 0
    llm_calls: int = 0
    done: bool = False


class WorkingMemory(BaseModel):
    """Bounded working memory: compressed history, facts, milestones."""

    max_events: int = 200
    facts: dict[str, str] = Field(default_factory=dict[str, str])
    milestones: list[str] = Field(default_factory=list[str])
    recent_events: list[str] = Field(default_factory=list[str])

    def remember_fact(self, key: str, value: str) -> None:
        self.facts[key] = value

    def record_event(self, event: str) -> None:
        self.recent_events.append(event)
        if len(self.recent_events) > self.max_events:
            # Raw history must not grow without bound: drop oldest first.
            del self.recent_events[: len(self.recent_events) - self.max_events]


class AgentDecision(BaseModel):
    reasoning: str = ""
    action: BrowserAction | None = None
    done: bool = False
    result_summary: str | None = None


class TraceEvent(BaseModel):
    schema_version: int = 1
    kind: str
    message: str
    session_id: str | None = None
    fields: dict[str, Any] = Field(default_factory=dict[str, Any])
