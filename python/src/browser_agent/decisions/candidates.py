"""Construct finite typed action candidates from semantic observation data."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from browser_agent._types import AgentObservation, BrowserAction, ElementRef
from browser_agent.decisions.base import DecisionProvider, DecisionProviderProtocolError


class CandidateKind(StrEnum):
    BROWSER_ACTION = "browser_action"
    ESCALATE_TO_PLANNER = "escalate_to_planner"


class ActionCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_id: str
    kind: CandidateKind
    description: str
    action_type: (
        Literal["click", "type", "select", "check", "scroll", "new_tab", "activate_tab"] | None
    ) = None
    target_ref: str | None = None
    text: str | None = None
    value: str | None = None
    checked: bool | None = None
    url: str | None = None
    tab: str | None = None
    dx: int = 0
    dy: int = 0
    observed_generation: int = 0

    def to_browser_action(self, resolved_target: ElementRef | None = None) -> BrowserAction | None:
        if self.kind == CandidateKind.ESCALATE_TO_PLANNER:
            if resolved_target is not None:
                raise ValueError("planner escalation cannot have a browser target")
            return None
        if self.action_type is None:
            raise ValueError("browser action candidate has no action type")
        target: ElementRef | None = None
        if self.target_ref is not None:
            if resolved_target is None or resolved_target.ref != self.target_ref:
                raise ValueError("candidate target must be resolved from its semantic reference")
            if resolved_target.generation < self.observed_generation:
                raise ValueError("resolved target predates the candidate observation")
            target = resolved_target
        elif resolved_target is not None:
            raise ValueError("non-target candidate cannot bind a browser element")

        return BrowserAction(
            type=self.action_type,
            target=target,
            text=self.text,
            value=self.value,
            checked=self.checked,
            url=self.url,
            tab=self.tab,
            dx=self.dx,
            dy=self.dy,
        )


@dataclass(frozen=True)
class CandidatePolicy:
    max_candidates: int = 16
    max_text_length: int = 2_000
    max_description_length: int = 512
    max_label_length: int = 120
    values_by_ref: Mapping[str, str] = field(default_factory=lambda: dict[str, str]())
    select_values_by_ref: Mapping[str, tuple[str, ...]] = field(
        default_factory=lambda: dict[str, tuple[str, ...]]()
    )
    scroll_delta: int = 600
    include_scroll: bool = True
    include_planner_escalation: bool = True

    def __post_init__(self) -> None:
        if not 2 <= self.max_candidates <= 16:
            raise ValueError("max_candidates must be between 2 and 16")
        if (
            self.max_text_length <= 0
            or self.max_description_length <= 0
            or self.max_label_length <= 0
            or self.scroll_delta <= 0
        ):
            raise ValueError("text and scroll bounds must be greater than zero")
        if any(len(value) > self.max_text_length for value in self.values_by_ref.values()):
            raise ValueError("candidate text exceeds max_text_length")
        if any(
            len(value) > self.max_text_length
            for values in self.select_values_by_ref.values()
            for value in values
        ):
            raise ValueError("candidate selection value exceeds max_text_length")


def build_action_candidates(
    task: str,
    current_subgoal: str,
    observation: AgentObservation,
    runtime_capabilities: set[str] | frozenset[str],
    policy: CandidatePolicy | None = None,
) -> list[ActionCandidate]:
    """Build at most 16 candidates; values must come from trusted task policy."""
    rules = policy or CandidatePolicy()
    candidates: list[ActionCandidate] = []
    capabilities = set(runtime_capabilities)
    task_context = " ".join(task.split())[: rules.max_label_length]
    goal_context = " ".join(current_subgoal.split())[: rules.max_label_length]

    def describe(action: str) -> str:
        description = f"Task: {task_context}; subgoal: {goal_context}; action: {action}"
        return description[: rules.max_description_length]

    for element in observation.elements:
        if not element.interactable:
            continue
        role = element.role.lower()
        label = (element.name or element.text or element.ref).replace("\n", " ").strip()
        label = label[: rules.max_label_length]
        if role in {"button", "link"} and "click" in capabilities:
            candidates.append(
                ActionCandidate(
                    candidate_id="",
                    kind=CandidateKind.BROWSER_ACTION,
                    description=describe(f"click {label} at {element.ref}"),
                    action_type="click",
                    target_ref=element.ref,
                    observed_generation=observation.state_generation,
                )
            )
        if role in {"checkbox", "radio", "switch"} and "check" in capabilities:
            desired = "checked" not in {state.lower() for state in element.state}
            candidates.append(
                ActionCandidate(
                    candidate_id="",
                    kind=CandidateKind.BROWSER_ACTION,
                    description=describe(f"set {label} at {element.ref} to {desired}"),
                    action_type="check",
                    checked=desired,
                    target_ref=element.ref,
                    observed_generation=observation.state_generation,
                )
            )
        if role in {"textbox", "searchbox", "text input"} and "type" in capabilities:
            text = rules.values_by_ref.get(element.ref)
            if text is not None:
                candidates.append(
                    ActionCandidate(
                        candidate_id="",
                        kind=CandidateKind.BROWSER_ACTION,
                        description=describe(
                            f"type the permitted value into {label} at {element.ref}"
                        ),
                        action_type="type",
                        text=text,
                        target_ref=element.ref,
                        observed_generation=observation.state_generation,
                    )
                )
        if role == "combobox" and "select" in capabilities:
            for value in rules.select_values_by_ref.get(element.ref, ()):
                candidates.append(
                    ActionCandidate(
                        candidate_id="",
                        kind=CandidateKind.BROWSER_ACTION,
                        description=describe(
                            f"select {value[: rules.max_label_length]} in {label}"
                        ),
                        action_type="select",
                        value=value,
                        target_ref=element.ref,
                        observed_generation=observation.state_generation,
                    )
                )

    if rules.include_scroll and "scroll" in capabilities:
        candidates.append(
            ActionCandidate(
                candidate_id="",
                kind=CandidateKind.BROWSER_ACTION,
                description=describe("scroll down to reveal more page content"),
                action_type="scroll",
                dy=rules.scroll_delta,
                observed_generation=observation.state_generation,
            )
        )
    if rules.include_planner_escalation:
        candidates.append(
            ActionCandidate(
                candidate_id="",
                kind=CandidateKind.ESCALATE_TO_PLANNER,
                description=describe("escalate to the reasoning planner"),
                observed_generation=observation.state_generation,
            )
        )

    action_candidates = candidates[: rules.max_candidates - 1]
    if len(candidates) > len(action_candidates):
        planner = next(
            (
                candidate
                for candidate in candidates
                if candidate.kind == CandidateKind.ESCALATE_TO_PLANNER
            ),
            None,
        )
        if planner is not None:
            action_candidates.append(planner)
    if len(action_candidates) < 2:
        raise ValueError("candidate construction produced fewer than two bounded choices")

    return [
        candidate.model_copy(update={"candidate_id": f"c{index:02d}"})
        for index, candidate in enumerate(action_candidates, start=1)
    ]


async def select_action_candidate(
    provider: DecisionProvider,
    *,
    task: str,
    current_subgoal: str,
    observation: AgentObservation,
    candidates: Sequence[ActionCandidate],
    run_id: str | None = None,
    step_id: int | None = None,
) -> ActionCandidate:
    """Ask System One to select only a supplied candidate identifier."""
    if not 2 <= len(candidates) <= 16:
        raise ValueError("System One candidate set must contain between 2 and 16 options")
    identifiers = {candidate.candidate_id for candidate in candidates}
    if len(identifiers) != len(candidates):
        raise ValueError("candidate identifiers must be unique")

    state: dict[str, Any] = {
        "task": task,
        "current_subgoal": current_subgoal,
        "run_id": run_id,
        "steps_taken": step_id,
        "observation": {
            "url": observation.url,
            "title": observation.title,
            "state_generation": observation.state_generation,
            "elements": [
                {
                    "ref": element.ref,
                    "role": element.role,
                    "name": element.name,
                    "text": element.text,
                    "state": element.state,
                    "interactable": element.interactable,
                }
                for element in observation.elements
            ],
        },
        "candidates": [
            {"id": candidate.candidate_id, "description": candidate.description}
            for candidate in candidates
        ],
    }
    options = {candidate.candidate_id: candidate.description for candidate in candidates}
    answer = await provider.choose(
        state,
        f"Task: {task}\nCurrent subgoal: {current_subgoal}\n"
        "Choose the single supplied candidate that best advances the current subgoal. "
        "Return only one candidate id; do not invent browser actions.",
        options,
    )
    if answer.accepted is not True:
        escalation = next(
            (
                candidate
                for candidate in candidates
                if candidate.kind == CandidateKind.ESCALATE_TO_PLANNER
            ),
            None,
        )
        if escalation is not None:
            return escalation
        raise DecisionProviderProtocolError(
            "System One abstained but the candidate set has no planner escalation."
        )

    candidate_id = str(answer.value)
    for candidate in candidates:
        if candidate.candidate_id == candidate_id:
            return candidate
    raise DecisionProviderProtocolError("System One returned an unknown candidate id.")
