"""A local plan for a fully explicit, currently grounded short user command."""

from __future__ import annotations

import re
from dataclasses import dataclass

from browser_agent._types import AgentDecision, AgentObservation, TaskState
from browser_agent.decisions.task_commands import UserCommand, user_commands
from browser_agent.decisions.task_search import (
    extract_task_search_query,
    task_search_values_by_ref,
)
from browser_agent.progress.evidence import task_terminal_text

_MAX_MICROTASK_OPERATIONS = 4
_SEARCH_START = re.compile(r"^\s*search\s+for\b", re.IGNORECASE)
_SEARCH_REQUEST = re.compile(
    r"\s*search\s+for\s+(?P<topic>[^.!?\r\n]{1,512}?)\s*\.?\s*",
    re.IGNORECASE,
)
_SEARCH_CONSTRAINT = re.compile(
    r"\b(?:and|then|on|from|in|with|without|under|over|below|above|between|"
    r"near|before|after|sort|filter|limit|only)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class MicrotaskPlan:
    commands: tuple[UserCommand, ...]
    terminal_text: tuple[str, ...]

    @property
    def milestones(self) -> list[str]:
        return [self._name(index, command) for index, command in enumerate(self.commands, 1)]

    @property
    def evidence(self) -> dict[str, str]:
        evidence = {
            self._name(index, command): command.evidence
            for index, command in enumerate(self.commands, 1)
        }
        if self.terminal_text:
            last = self.milestones[-1]
            evidence[last] += " ; " + " ; ".join(
                f"visible_text:{text}" for text in self.terminal_text
            )
        return evidence

    def attach(self, decision: AgentDecision) -> AgentDecision:
        if decision.action is None:
            return decision
        return decision.model_copy(
            update={
                "milestones": self.milestones,
                "milestone_evidence": self.evidence,
                "plan_initialized": True,
                "current_subgoal": self.milestones[0],
                "next_milestone": self.milestones[1] if len(self.commands) > 1 else None,
            }
        )

    @staticmethod
    def _name(index: int, command: UserCommand) -> str:
        return f"User command {index}: {command.kind} {command.label}"


def grounded_microtask(task: TaskState, observation: AgentObservation) -> MicrotaskPlan | None:
    """Do not skip planning for unknown intent, future controls, or ambiguity."""
    goal = task.user_goal or task.task
    if _SEARCH_START.match(goal):
        return _grounded_search_microtask(task, goal, observation)

    commands = user_commands(goal, observation, require_complete=True)
    if commands is None or len(commands) > _MAX_MICROTASK_OPERATIONS:
        return None
    return MicrotaskPlan(commands, tuple(task_terminal_text(task)))


def _grounded_search_microtask(
    task: TaskState,
    goal: str,
    observation: AgentObservation,
) -> MicrotaskPlan | None:
    match = _SEARCH_REQUEST.fullmatch(goal)
    if match is None:
        return None
    topic = " ".join(match.group("topic").split())
    if topic.startswith(('"', "'")) or topic.endswith(('"', "'")):
        if len(topic) < 2 or topic[0] not in {'"', "'"} or topic[-1] != topic[0]:
            return None
        topic = topic[1:-1]
    if '"' in topic or "'" in topic:
        return None
    if not topic or _SEARCH_CONSTRAINT.search(topic):
        return None
    if extract_task_search_query(goal) != topic:
        return None

    bindings = task_search_values_by_ref(goal, observation)
    if len(bindings) != 1:
        return None
    field_ref = next(iter(bindings))
    fields = [element for element in observation.elements if element.ref == field_ref]
    if len(fields) != 1:
        return None
    field = fields[0]
    buttons = [
        element
        for element in observation.elements
        if element.role.casefold() == "button"
        and " ".join((element.name or "").split()).casefold() == "search"
        and element.interactable
        and "disabled" not in {state.casefold() for state in element.state}
    ]
    if len(buttons) != 1:
        return None

    commands = (
        UserCommand("type", field.ref, field.name or "Search", bindings[field_ref]),
        UserCommand("click", buttons[0].ref, "Search"),
    )
    return MicrotaskPlan(commands, tuple(task_terminal_text(task)))
