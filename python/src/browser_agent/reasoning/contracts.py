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


class ReasoningEffort(StrEnum):
    NONE = "none"
    LOW = "low"
    HIGH = "high"


class ReasoningPurpose(StrEnum):
    PLAN = "plan"
    REPLAN = "replan"
    RESOLVE_AMBIGUITY = "resolve_ambiguity"
    INTERPRET_STATE = "interpret_state"


class ReasoningOutcome(StrEnum):
    MILESTONE_PLAN = "milestone_plan"
    NEXT_ACTION = "next_action"
    ASK_USER = "ask_user"
    INTERPRETATION = "interpretation"


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
    candidate_actions: list[ReasoningAction] = Field(
        default_factory=list[ReasoningAction], max_length=8
    )
    questions: list[str] = Field(default_factory=list[str], max_length=10)

    @model_validator(mode="after")
    def validate_outcome(self) -> ReasoningDecision:
        if self.outcome == ReasoningOutcome.NEXT_ACTION:
            if (self.action is None) == (not self.candidate_actions):
                raise ValueError(
                    "next_action requires exactly one action or a non-empty candidate set"
                )
            if self.milestones:
                raise ValueError("next_action cannot contain a milestone plan")
        elif self.action is not None or self.candidate_actions:
            raise ValueError("only next_action decisions may contain browser actions")

        if self.outcome == ReasoningOutcome.MILESTONE_PLAN and not self.milestones:
            raise ValueError("milestone_plan requires at least one milestone")
        if self.outcome == ReasoningOutcome.MILESTONE_PLAN:
            if set(self.milestone_evidence) != set(self.milestones):
                raise ValueError(
                    "each milestone requires one deterministic visible evidence phrase"
                )
            if any(not evidence.strip() for evidence in self.milestone_evidence.values()):
                raise ValueError("milestone evidence phrases must not be empty")
        elif self.milestone_evidence:
            raise ValueError("milestone evidence is only valid with a milestone plan")
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
    failure_summary: str | None = Field(default=None, max_length=1_000)


class ReasoningProvider(Protocol):
    """Domain API implemented by the configured reasoning model adapter."""

    async def reason(
        self,
        context: ReasoningContext,
        *,
        model: str,
        effort: ReasoningEffort,
    ) -> ReasoningDecision: ...
