"""Provider-neutral typed decision contracts."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, TypedDict, cast

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
    model: str | None = None
    question_kinds: tuple[str, ...] = ()
    error_type: str | None = None
    fallback_from: str | None = None
    fallback_to: str | None = None
    fallback_reason: str | None = None
    run_id: str | None = None
    step: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None


DecisionTelemetry = Callable[[DecisionTelemetryEvent], None]


class TelemetryCorrelation(TypedDict):
    run_id: str | None
    step: int | None


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
        model=event.model,
        elapsed_ms=round(event.elapsed_ms, 3),
        question_kinds=event.question_kinds,
        error_type=event.error_type,
        fallback_from=event.fallback_from,
        fallback_to=event.fallback_to,
        fallback_reason=event.fallback_reason,
        run_id=event.run_id,
        step=event.step,
        input_tokens=event.input_tokens,
        output_tokens=event.output_tokens,
    )
    if callback is not None:
        callback(event)


def correlation_fields(state: str | Mapping[str, Any]) -> TelemetryCorrelation:
    """Extract bounded, non-content correlation values from an existing state map."""
    if not isinstance(state, Mapping):
        return {"run_id": None, "step": None}
    raw_run_id = state.get("run_id")
    run_id = None
    if isinstance(raw_run_id, str):
        safe = "".join(char for char in raw_run_id[:128] if char.isalnum() or char in "-_.:")
        run_id = safe or None
    raw_step = state.get("steps_taken")
    step = (
        raw_step
        if isinstance(raw_step, int) and not isinstance(raw_step, bool) and raw_step >= 0
        else None
    )
    return {"run_id": run_id, "step": step}


def response_usage_counts(response: object) -> tuple[int | None, int | None]:
    """Read only provider-reported token counts; never estimate tokens or cost."""
    usage = _get_value(response, "usage")
    if usage is None:
        return None, None
    input_tokens = _valid_token_count(_get_value(usage, "input_tokens"))
    output_tokens = _valid_token_count(_get_value(usage, "output_tokens"))
    return input_tokens, output_tokens


def response_model_name(response: object, default: str) -> str:
    """Read a short provider model label while excluding arbitrary response content."""
    raw = _get_value(response, "model") if response is not None else None
    if not isinstance(raw, str) or not raw:
        return default
    return "".join(char for char in raw[:128] if char.isalnum() or char in "-_.:") or default


def _get_value(value: object, name: str) -> object | None:
    if isinstance(value, Mapping):
        return cast(Mapping[str, Any], value).get(name)
    return getattr(value, name, None)


def _valid_token_count(value: object | None) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 2**63 - 1:
        return value
    return None


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
