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

from pydantic import AliasChoices, BaseModel, Field, model_validator


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


class RecoveryStep(StrEnum):
    MECHANICAL_REPAIR = "mechanical_repair"
    REOBSERVE = "reobserve"
    ALTERNATE_ACTION = "alternate_bounded_action"
    SYSTEM_ONE_CLASSIFICATION = "system_one_classification"
    LUNA_NORMAL_REPLAN = "luna_normal_replan"
    COMPLEXITY_GATE = "complexity_gate"
    LUNA_HIGH_REPLAN = "luna_high_replan"
    ASK_USER = "ask_user"
    TERMINATE = "terminate"


class RecoveryDecision(BaseModel):
    decision: Literal["retry", "reacquire_and_retry", "replan", "escalate", "ask_user", "terminate"]
    attempt: int = 0
    max_attempts: int = 3
    reason: str = ""
    step: RecoveryStep = RecoveryStep.LUNA_NORMAL_REPLAN


class TaskState(BaseModel):
    """Checkpoint-safe task goal, milestones, and explicit bounded budgets."""

    task: str
    user_goal: str | None = None
    goal: str | None = None
    constraints: list[str] = Field(default_factory=list[str], max_length=50)
    milestones: list[str] = Field(default_factory=list[str], max_length=50)
    required_milestones: list[str] = Field(default_factory=list[str], max_length=50)
    completed: list[str] = Field(default_factory=list[str], max_length=50)
    current_subgoal: str | None = None
    next_milestone: str | None = None
    milestone_evidence: dict[str, str] = Field(
        default_factory=lambda: dict[str, str](),
    )
    required_evidence: list[str] = Field(default_factory=list[str], max_length=30)
    deterministic_evidence: list[str] = Field(default_factory=list[str], max_length=30)
    failed_strategies: list[str] = Field(default_factory=list[str], max_length=50)
    steps_taken: int = Field(default=0, ge=0)
    llm_calls: int = Field(default=0, ge=0)
    recovery_count: int = Field(default=0, ge=0)
    replan_count: int = Field(default=0, ge=0)
    stagnant_steps: int = Field(default=0, ge=0)
    recovery_history: list[dict[str, Any]] = Field(
        default_factory=list[dict[str, Any]], max_length=50
    )
    progress_signals: list[str] = Field(default_factory=list[str], max_length=20)
    status: Literal["running", "awaiting_user", "pending_confirmation", "completed", "failed"] = (
        "running"
    )
    run_id: str | None = None
    result_summary: str | None = None
    done: bool = False

    @model_validator(mode="after")
    def default_goal(self) -> TaskState:
        if self.user_goal is None:
            self.user_goal = self.goal or self.task
        if self.goal is None:
            self.goal = self.user_goal
        if not self.required_milestones and self.milestones:
            self.required_milestones = list(self.milestones)
        return self


class WorkingMemory(BaseModel):
    """Bounded structured memory; raw conversation and snapshots are not stored."""

    max_events: int = Field(default=20, ge=0, le=50)
    user_goal: str = ""
    constraints: list[str] = Field(default_factory=list[str], max_length=50)
    completed_milestones: list[str] = Field(default_factory=list[str], max_length=50)
    current_subgoal: str | None = None
    acquired_facts: dict[str, str] = Field(
        default_factory=lambda: dict[str, str](),
        validation_alias=AliasChoices("acquired_facts", "facts"),
    )
    relevant_entities: list[str] = Field(default_factory=list[str], max_length=100)
    failed_strategies: list[str] = Field(default_factory=list[str], max_length=50)
    irreversible_actions: list[str] = Field(default_factory=list[str], max_length=50)
    pending_questions: list[str] = Field(default_factory=list[str], max_length=50)
    next_milestone: str | None = None
    checkpoint_summary: str = Field(default="", max_length=2_000)
    recent_events: list[str] = Field(
        default_factory=list[str],
        max_length=50,
        validation_alias=AliasChoices("recent_events", "recent_steps"),
    )

    @property
    def facts(self) -> dict[str, str]:
        """Compatibility view for existing agent code and older checkpoints."""
        return self.acquired_facts

    @property
    def recent_steps(self) -> list[str]:
        return self.recent_events

    def remember_fact(self, key: str, value: str) -> None:
        normalized_key = key.strip()[:120]
        if not normalized_key:
            raise ValueError("fact key cannot be empty")
        if normalized_key not in self.acquired_facts and len(self.acquired_facts) >= 100:
            oldest_key = next(iter(self.acquired_facts))
            del self.acquired_facts[oldest_key]
        self.acquired_facts[normalized_key] = value.strip()[:1_000]

    def _append_bounded(self, field_name: str, value: str, limit: int) -> None:
        values = getattr(self, field_name)
        values.append(" ".join(value.split())[:300])
        if len(values) > limit:
            del values[: len(values) - limit]

    def remember_entity(self, entity: str) -> None:
        self._append_bounded("relevant_entities", entity, 100)

    def record_failed_strategy(self, strategy: str) -> None:
        self._append_bounded("failed_strategies", strategy, 50)

    def record_irreversible_action(self, action: str) -> None:
        self._append_bounded("irreversible_actions", action, 50)

    def add_pending_question(self, question: str) -> None:
        self._append_bounded("pending_questions", question, 50)

    def complete_milestone(self, milestone: str) -> None:
        if milestone not in self.completed_milestones:
            self._append_bounded("completed_milestones", milestone, 50)

    def record_event(self, event: str) -> None:
        if self.max_events == 0:
            return
        self.recent_events.append(" ".join(event.split())[:300])
        if len(self.recent_events) > self.max_events:
            del self.recent_events[: len(self.recent_events) - self.max_events]


class AgentDecision(BaseModel):
    reasoning: str = ""
    action: BrowserAction | None = None
    done: bool = False
    completed_milestone: str | None = None
    result_summary: str | None = None


class TraceEvent(BaseModel):
    schema_version: int = 1
    kind: str
    message: str
    session_id: str | None = None
    fields: dict[str, Any] = Field(default_factory=dict[str, Any])
