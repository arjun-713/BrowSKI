"""Closed OpenAI output schema, converted to the provider-neutral contract."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from browser_agent._types import TaskState
from browser_agent.browser_code.contracts import BrowserCodeProposal
from browser_agent.reasoning.contracts import (
    ReasoningAction,
    ReasoningDecision,
    ReasoningOutcome,
)


class LunaMilestoneEvidence(BaseModel):
    """Explicit entries replace arbitrary object keys in strict JSON output."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    milestone: str = Field(min_length=1)
    evidence: str = Field(min_length=1)


class LunaDecisionOutput(BaseModel):
    """Vendor wire format only; runtime policy still validates ReasoningDecision."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    outcome: ReasoningOutcome
    summary: str = Field(default="", max_length=2_000)
    milestones: list[str] = Field(default_factory=list[str], max_length=10)
    milestone_evidence: list[LunaMilestoneEvidence] = Field(
        default_factory=list[LunaMilestoneEvidence], max_length=10
    )
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

    def to_decision(self, task: TaskState | None = None) -> ReasoningDecision:
        if self.candidate_id is not None and self.candidate_ids:
            raise ValueError("candidate_id and candidate_ids cannot be combined")

        evidence: dict[str, str] = {}
        for entry in self.milestone_evidence:
            if entry.milestone in evidence:
                raise ValueError("duplicate milestone evidence entry")
            evidence[entry.milestone] = entry.evidence
        payload = self.model_dump(mode="json")
        payload["milestone_evidence"] = evidence
        if self.outcome == ReasoningOutcome.NEXT_ACTION and (
            self.candidate_id is not None or self.candidate_ids
        ):
            # Candidate IDs resolve only against the current runtime-owned set.
            # A vendor may also return legacy action fields; they are not a
            # second source of authority and must not conflict with the ID.
            payload["action"] = None
            payload["candidate_actions"] = []
        if self.outcome == ReasoningOutcome.MILESTONE_PLAN and self.action is None:
            # A vendor may include suggested actions with a plan. Discard them;
            # planning never authorizes or queues execution. The next decision
            # must select from newly observed runtime candidates.
            payload["candidate_actions"] = []
            payload["candidate_id"] = None
            payload["candidate_ids"] = []
        if (
            self.outcome == ReasoningOutcome.NEXT_ACTION
            and self.milestones
            and task is not None
            and self.milestones == task.milestones
            and evidence == task.milestone_evidence
        ):
            # Repeated known plan data is not a new plan or action authority.
            # Unknown/changed plans still fail the closed domain contract.
            payload["milestones"] = []
            payload["milestone_evidence"] = {}
        return ReasoningDecision.model_validate(payload)
