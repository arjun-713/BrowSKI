"""Experimental Laya routing for a closed, locally authorized command family."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from browser_agent._types import AgentObservation, SemanticSnapshot, TaskState
from browser_agent.decisions.base import DecisionAnswer, DecisionProvider, DecisionProviderError
from browser_agent.decisions.candidates import ActionCandidate, CandidatePolicy
from browser_agent.decisions.task_commands import UserCommand, user_commands
from browser_agent.progress.evidence import local_browser_checks
from browser_agent.telemetry.debug_log import record_debug

_CONSEQUENTIAL = re.compile(
    r"\b(?:submit|send|buy|purchase|pay|delete|publish|reserve|password|security|account)\b",
    re.I,
)
_INSTRUCTION = (
    "Choose the next authorized user command. Prerequisites have been checked locally. "
    "Choose ESCALATE_TO_REASONER if the proposed operation is not safely justified."
)


class LayaRoutingPolicy(BaseModel):
    """Thresholds apply only to this checkpoint, template, and closed family."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    policy_id: str = Field(min_length=1)
    checkpoint: str = Field(min_length=1)
    benchmark_sha256: str = Field(min_length=64, max_length=64)
    template_version: str = "explicit-command-v1"
    enabled: bool = False
    answer_confidence_threshold: float | None = Field(default=None, ge=0, le=1)
    minimum_margin: float | None = Field(default=None, ge=0, le=1)

    @classmethod
    def load(cls, path: Path) -> LayaRoutingPolicy:
        return cls.model_validate_json(path.read_text(encoding="utf-8"))


@dataclass(frozen=True)
class LocalRoute:
    candidate: ActionCandidate | None
    reason: str
    confidence: float | None = None
    margin: float | None = None


def next_explicit_candidate(
    task: TaskState,
    snapshot: SemanticSnapshot,
    observation: AgentObservation,
    candidates: list[ActionCandidate],
    policy: CandidatePolicy,
) -> tuple[UserCommand, ActionCandidate] | None:
    """Fail closed outside complete short commands grounded in this observation.

    Code establishes intent, prerequisites, exact values, and completion facts.
    This is deliberately narrower than general next-action reasoning.
    """
    commands = user_commands(task.user_goal or task.task, observation, require_complete=True)
    if not commands or len(commands) > 4 or task.recovery_streak:
        return None
    checks = local_browser_checks(task, snapshot, observation, policy)
    command = next((item for item in commands if not checks.get(item.evidence, False)), None)
    if command is None or _CONSEQUENTIAL.search(command.label):
        return None
    matches = [
        candidate
        for candidate in candidates
        if candidate.action_type == command.kind
        and candidate.target_ref == command.ref
        and (command.kind != "type" or candidate.text == command.value)
        and (command.kind != "select" or candidate.value == command.value)
        and (command.kind != "check" or candidate.checked == command.checked)
    ]
    return (command, matches[0]) if len(matches) == 1 else None


async def choose_explicit_command(
    provider: DecisionProvider,
    policy: LayaRoutingPolicy,
    command: UserCommand,
    candidate: ActionCandidate,
    task: TaskState,
) -> LocalRoute:
    """No raw form value, page instructions, or unrelated state enters Laya."""
    if provider.name != "laya" or not policy.enabled:
        return LocalRoute(None, "policy_disabled")
    if policy.answer_confidence_threshold is None or policy.minimum_margin is None:
        return LocalRoute(None, "uncalibrated")
    state = {
        "run_id": task.run_id,
        "steps_taken": task.steps_taken,
        "user_command": _safe_description(command),
        "authorization": "Exact target and value authorized locally by user instruction.",
        "prerequisites": "All preceding commands verified; target currently interactable.",
    }
    options = {
        "EXECUTE_AUTHORIZED_COMMAND": _safe_description(command),
        "ESCALATE_TO_REASONER": "Ask the reasoning provider to review this decision.",
    }
    try:
        answer = await provider.choose(state, _INSTRUCTION, options)
    except DecisionProviderError as exc:
        return LocalRoute(None, type(exc).__name__)
    confidence, margin = answer_metrics(answer)
    reason = "accepted"
    if answer.value != "EXECUTE_AUTHORIZED_COMMAND":
        reason = "abstained"
    elif confidence is None or margin is None:
        reason = "missing_metrics"
    elif confidence < policy.answer_confidence_threshold or margin < policy.minimum_margin:
        reason = "below_threshold"
    accepted = reason == "accepted"
    record_debug(
        "decision.local_route",
        {
            "outcome": "accepted" if accepted else "fallback",
            "candidate_id": candidate.candidate_id if accepted else None,
            "family": "explicit_commands",
            "answer_confidence": confidence,
            "margin": margin,
            "reason": reason,
            "policy_id": policy.policy_id,
        },
        step=task.steps_taken + 1,
    )
    return LocalRoute(candidate if accepted else None, reason, confidence, margin)


def answer_metrics(answer: DecisionAnswer) -> tuple[float | None, float | None]:
    raw = answer.raw or {}
    value = raw.get("answer_confidence")
    confidence = float(value) if isinstance(value, (int, float)) and 0 <= value <= 1 else None
    probabilities = sorted(answer.probabilities.values(), reverse=True)
    margin = probabilities[0] - probabilities[1] if len(probabilities) >= 2 else None
    return confidence, margin


def _safe_description(command: UserCommand) -> str:
    # Accessible names are still untrusted page data, never instructions. JSON
    # encoding preserves this distinction and values stay entirely local.
    label = json.dumps(command.label[:120], ensure_ascii=True)
    description = f"{command.kind} the user-named control {label}"
    if command.kind in {"type", "select"}:
        description += " using the exact locally authorized value"
    elif command.kind == "check":
        description += f" to checked={command.checked}"
    return description
