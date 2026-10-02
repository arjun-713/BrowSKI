"""Provider-neutral typed decision contracts."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import structlog


class DecisionKind(StrEnum):
    CHOICE = "choice"
    SCORE = "score"
    NOUL = "noul"


@dataclass(frozen=True)
class DecisionQuestion:
    kind: DecisionKind
    instructions: str
    criteria: Mapping[str, str | None] | tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        if not self.instructions.strip():
            raise ValueError("decision instructions cannot be empty")
        if self.kind == DecisionKind.CHOICE:
            if not isinstance(self.criteria, Mapping) or not 2 <= len(self.criteria) <= 16:
                raise ValueError("choice decisions require 2 to 16 named options")
        elif self.kind == DecisionKind.SCORE:
            if not isinstance(self.criteria, tuple) or not 2 <= len(self.criteria) <= 8:
                raise ValueError("score decisions require an ordered rubric of 2 to 8 levels")
        elif self.criteria is not None:
            raise ValueError("noul decisions do not take criteria")


@dataclass(frozen=True)
class DecisionAnswer:
    kind: DecisionKind
    value: str | float | bool
    probabilities: Mapping[str, float] = field(default_factory=lambda: dict[str, float]())
    confidence_raw: float | None = None
    confidence_calibrated: float | None = None
    accepted: bool | None = None
    raw: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class DecisionResult:
    provider: str
    model: str | None
    answers: Mapping[str, DecisionAnswer]
    calibration_id: str | None = None
    fallback_from: str | None = None
    fallback_reason: str | None = None


@dataclass(frozen=True)
class DecisionTelemetryEvent:
    provider: str
    operation: str
    outcome: str
    elapsed_ms: float
    question_kinds: tuple[str, ...] = ()
    error_type: str | None = None
    fallback_from: str | None = None


DecisionTelemetry = Callable[[DecisionTelemetryEvent], None]


@dataclass(frozen=True)
class ProviderHealth:
    provider: str
    available: bool
    endpoint: str | None = None
    detail: str | None = None


class DecisionProviderError(RuntimeError):
    """Base for provider failures safe to expose to the agent runtime."""


class DecisionProviderUnavailable(DecisionProviderError):
    """Provider endpoint or local runtime is unavailable."""


class DecisionProviderTimeout(DecisionProviderError):
    """Provider call exceeded its configured time budget."""


class DecisionProviderProtocolError(DecisionProviderError):
    """Provider response did not match the typed decision contract."""


_logger: Any = structlog.get_logger("browser_agent.decisions")


def emit_telemetry(callback: DecisionTelemetry | None, event: DecisionTelemetryEvent) -> None:
    """Emit provider and timing metadata without browser state or answer values."""
    _logger.info(
        "decision_provider_event",
        provider=event.provider,
        operation=event.operation,
        outcome=event.outcome,
        elapsed_ms=round(event.elapsed_ms, 3),
        question_kinds=event.question_kinds,
        error_type=event.error_type,
        fallback_from=event.fallback_from,
    )
    if callback is not None:
        callback(event)


@dataclass(frozen=True)
class DecisionCapabilities:
    choice: bool = True
    score: bool = True
    noul: bool = True
    semantic_verification: bool = True
    recovery_classification: bool = True
    progress_checks: bool = True


class DecisionProvider(ABC):
    """System One interface; provider confidence is interpreted by its own policy."""

    name: str

    @property
    def capabilities(self) -> DecisionCapabilities:
        return DecisionCapabilities()

    @abstractmethod
    async def evaluate(
        self, state: str | Mapping[str, Any], questions: Mapping[str, DecisionQuestion]
    ) -> DecisionResult:
        """Evaluate bounded typed questions against a state snapshot."""

    async def choose(
        self,
        state: str | Mapping[str, Any],
        instructions: str,
        options: Mapping[str, str | None],
    ) -> DecisionAnswer:
        result = await self.evaluate(
            state, {"decision": DecisionQuestion(DecisionKind.CHOICE, instructions, options)}
        )
        return result.answers["decision"]

    async def score(
        self, state: str | Mapping[str, Any], instructions: str, rubric: tuple[str, ...]
    ) -> DecisionAnswer:
        result = await self.evaluate(
            state, {"decision": DecisionQuestion(DecisionKind.SCORE, instructions, rubric)}
        )
        return result.answers["decision"]

    async def probability(
        self, state: str | Mapping[str, Any], instructions: str
    ) -> DecisionAnswer:
        result = await self.evaluate(
            state, {"decision": DecisionQuestion(DecisionKind.NOUL, instructions)}
        )
        return result.answers["decision"]

    async def semantic_verify(
        self, state: str | Mapping[str, Any], expected: str
    ) -> DecisionAnswer:
        return await self.probability(
            state, f"Does the observed browser state confirm this expected result: {expected}?"
        )

    async def classify_recovery(
        self, state: str | Mapping[str, Any], failure: str
    ) -> DecisionAnswer:
        return await self.choose(
            state,
            f"Choose the safest recovery for this browser failure: {failure}",
            {
                "retry": "Retry the same action once when it remains safe.",
                "reacquire": "Refresh semantic references, then retry once.",
                "replan": "Choose a different bounded action from the new state.",
                "escalate": "Stop automation and request higher-level reasoning or help.",
            },
        )

    async def check_progress(
        self, state: str | Mapping[str, Any], goal: str, previous_state: str
    ) -> DecisionAnswer:
        return await self.probability(
            state,
            f"Has browser state made measurable progress toward {goal}? "
            f"Previous state: {previous_state}",
        )
