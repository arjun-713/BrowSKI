"""Provider-neutral contracts for bounded GPT reasoning calls."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from browser_agent._types import (
    AgentObservation,
    BrowserAction,
    ElementRef,
    TaskState,
    WorkingMemory,
)
from browser_agent.browser_code.contracts import BrowserCodeProposal, BrowserCodeResult


class ReasoningEffort(StrEnum):
    NONE = "none"
    LOW = "low"
    HIGH = "high"


class ReasoningPurpose(StrEnum):
    PLAN = "plan"
    REPLAN = "replan"
    RESOLVE_AMBIGUITY = "resolve_ambiguity"
    INTERPRET_STATE = "interpret_state"
    CHOOSE_ACTION = "choose_action"


class ReasoningOutcome(StrEnum):
    MILESTONE_PLAN = "milestone_plan"
    TASK_COMPLETE = "task_complete"
    NEXT_ACTION = "next_action"
    ASK_USER = "ask_user"
    INTERPRETATION = "interpretation"
    BROWSER_CODE = "browser_code"


BrowserActionType = Literal[
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

_TARGET_ACTIONS = {"click", "type", "select", "check", "hover"}


class ReasoningAction(BaseModel):
    """Closed model output shape; element targets are semantic references only."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    type: BrowserActionType
    target_ref: str | None = Field(default=None, min_length=1, max_length=200)
    text: str | None = Field(default=None, max_length=2_000)
    clear: bool = True
    submit: bool = False
    value: str | None = Field(default=None, max_length=2_000)
    by: Literal["value", "label"] = "value"
    checked: bool | None = None
    key: str | None = Field(default=None, max_length=100)
    dx: int = 0
    dy: int = 0
    url: str | None = Field(default=None, max_length=4_096)
    tab: str | None = Field(default=None, max_length=200)
    accept: bool | None = None
    ms: int | None = Field(default=None, ge=0, le=30_000)

    @model_validator(mode="after")
    def validate_action_shape(self) -> ReasoningAction:
        if self.type in _TARGET_ACTIONS and self.target_ref is None:
            raise ValueError(f"{self.type} action requires a semantic target_ref")
        if self.type == "type" and self.text is None:
            raise ValueError("type action requires text")
        if self.type == "select" and self.value is None:
            raise ValueError("select action requires value")
        if self.type == "check" and self.checked is None:
            raise ValueError("check action requires checked")
        if self.type == "navigate" and self.url is None:
            raise ValueError("navigate action requires url")
        if self.target_ref is not None and not self.target_ref.startswith("@"):
            raise ValueError("target_ref must be a semantic reference")
        return self

    def bind(self, observation: AgentObservation) -> BrowserAction:
        """Bind a model-selected semantic ref to the current observation."""
        target: ElementRef | None = None
        if self.target_ref is not None:
            element = next(
                (item for item in observation.elements if item.ref == self.target_ref),
                None,
            )
            if element is None:
                raise ValueError(
                    f"semantic target {self.target_ref!r} is absent from the current observation"
                )
            if not element.interactable:
                raise ValueError(f"semantic target {self.target_ref!r} is not interactable")
            target = ElementRef(
                ref=element.ref,
                generation=observation.state_generation,
            )

        action_data = self.model_dump(exclude={"target_ref"}, exclude_none=True)
        action_data["target"] = target
        return BrowserAction.model_validate(action_data)


class ReasoningDecision(BaseModel):
    """Structured one-step plan, action, interpretation, or user escalation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    outcome: ReasoningOutcome
    summary: str = Field(default="", max_length=2_000)
    milestones: list[str] = Field(default_factory=list[str], max_length=10)
    milestone_evidence: dict[str, str] = Field(default_factory=dict[str, str], max_length=10)
    current_subgoal: str | None = Field(default=None, max_length=500)
    action: ReasoningAction | None = None
    evidence_ref: str | None = Field(default=None, min_length=2, max_length=200)
    browser_code: BrowserCodeProposal | None = None
    candidate_actions: list[ReasoningAction] = Field(
        default_factory=list[ReasoningAction], max_length=8
    )
    candidate_id: str | None = Field(default=None, pattern=r"^c\d{2}$")
    candidate_ids: list[str] = Field(default_factory=list[str], max_length=4)
    questions: list[str] = Field(default_factory=list[str], max_length=10)

    @model_validator(mode="after")
    def validate_outcome(self) -> ReasoningDecision:
        if len(set(self.candidate_ids)) != len(self.candidate_ids):
            raise ValueError("candidate ID batches must not repeat an action")
        for index, action in enumerate(self.candidate_actions):
            if action in self.candidate_actions[:index]:
                raise ValueError("action batches must not repeat an identical action")
        if self.outcome == ReasoningOutcome.NEXT_ACTION:
            if (
                sum(
                    (
                        self.action is not None,
                        bool(self.candidate_actions),
                        self.candidate_id is not None,
                        bool(self.candidate_ids),
                    )
                )
                != 1
            ):
                raise ValueError(
                    "next_action requires exactly one action, batch, candidate ID, or ID batch"
                )
            if self.milestones:
                raise ValueError("next_action cannot contain a milestone plan")
            if self.browser_code is not None:
                raise ValueError("next_action cannot contain a browser-code proposal")
            if self.evidence_ref is not None and self.action is None and self.candidate_id is None:
                raise ValueError("evidence_ref requires one next_action")
        elif self.outcome == ReasoningOutcome.BROWSER_CODE:
            if self.browser_code is None:
                raise ValueError("browser_code outcome requires one proposal")
            if (
                self.action is not None
                or self.candidate_actions
                or self.milestones
                or self.milestone_evidence
                or self.current_subgoal is not None
                or self.questions
                or self.candidate_id is not None
                or self.candidate_ids
            ):
                raise ValueError("browser_code cannot combine with action, plan, or user control")
        elif (
            self.action is not None
            or self.candidate_actions
            or self.browser_code is not None
            or self.evidence_ref is not None
            or self.candidate_id is not None
            or self.candidate_ids
        ):
            raise ValueError("only next_action decisions may contain browser actions")
        if self.evidence_ref is not None and not self.evidence_ref.startswith("@"):
            raise ValueError("evidence_ref must be a semantic reference")

        if self.outcome in {ReasoningOutcome.MILESTONE_PLAN, ReasoningOutcome.TASK_COMPLETE}:
            if not self.milestones:
                raise ValueError(f"{self.outcome.value} requires at least one milestone")
            if len(set(self.milestones)) != len(self.milestones):
                raise ValueError("milestone identifiers must be unique")
            if set(self.milestone_evidence) != set(self.milestones):
                raise ValueError(
                    "each milestone requires one deterministic visible evidence phrase"
                )
            if any(not evidence.strip() for evidence in self.milestone_evidence.values()):
                raise ValueError("milestone evidence phrases must not be empty")
        elif self.milestone_evidence:
            raise ValueError("milestone evidence is only valid with a milestone plan or completion")
        if self.outcome == ReasoningOutcome.TASK_COMPLETE and self.questions:
            raise ValueError("task_complete cannot include user questions")
        if self.outcome == ReasoningOutcome.ASK_USER and not self.questions:
            raise ValueError("ask_user requires at least one question")
        if any(not milestone.strip() for milestone in self.milestones):
            raise ValueError("milestones must not be empty")
        if any(not question.strip() for question in self.questions):
            raise ValueError("questions must not be empty")
        return self

    def bind_actions(self, observation: AgentObservation) -> list[BrowserAction]:
        """Resolve all semantic refs using the observation used for this decision."""
        actions: list[ReasoningAction] = list(self.candidate_actions)
        if self.action is not None:
            actions.append(self.action)
        return [action.bind(observation) for action in actions]


class ReasoningContext(BaseModel):
    """Compact task context that excludes raw DOM and selector-based targets."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    purpose: ReasoningPurpose
    task: TaskState
    memory: WorkingMemory
    observation: AgentObservation
    prior_summary: str = Field(default="", max_length=2_000)
    visual_observation: str | None = Field(default=None, max_length=1_200)
    failure_summary: str | None = Field(default=None, max_length=1_000)
    candidate_options: dict[str, str] = Field(default_factory=dict, max_length=16)
    browser_checks: dict[str, bool] = Field(default_factory=dict, max_length=64)
    task_tab_labels: dict[str, str] = Field(default_factory=dict, max_length=8)
    browser_code_enabled: bool = False
    browser_code_result: BrowserCodeResult | None = None


class ReasoningProvider(Protocol):
    """Domain API implemented by the configured reasoning model adapter."""

    async def reason(
        self,
        context: ReasoningContext,
        *,
        model: str,
        effort: ReasoningEffort,
    ) -> ReasoningDecision: ...
