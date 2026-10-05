"""Laya-first routing with provider-local acceptance and Jev fallback."""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from browser_agent.decisions.base import (
    DecisionProvider,
    DecisionQuestion,
    DecisionResult,
    DecisionTelemetry,
    DecisionTelemetryEvent,
    correlation_fields,
    emit_telemetry,
)


class AdaptiveDecisionProvider(DecisionProvider):
    """Try Laya first; use Jev only when Laya errors or its own policy abstains."""

    name = "adaptive"

    def __init__(
        self,
        laya: DecisionProvider,
        jev: DecisionProvider,
        *,
        fallback_to_jev: bool = True,
        telemetry: DecisionTelemetry | None = None,
    ) -> None:
        self.laya = laya
        self.jev = jev
        self.fallback_to_jev = fallback_to_jev
        self.telemetry = telemetry

    async def evaluate(
        self, state: str | Mapping[str, Any], questions: Mapping[str, DecisionQuestion]
    ) -> DecisionResult:
        started = time.perf_counter()
        try:
            result = await self.laya.evaluate(state, questions)
        except Exception as exc:
            if not self.fallback_to_jev:
                emit_telemetry(
                    self.telemetry,
                    DecisionTelemetryEvent(
                        self.name,
                        "fallback",
                        "disabled",
                        (time.perf_counter() - started) * 1000,
                        error_type=type(exc).__name__,
                        fallback_to="jev",
                        fallback_reason=f"laya_error:{type(exc).__name__}",
                        **correlation_fields(state),
                    ),
                )
                raise
            return await self._fallback(
                state, questions, reason=f"laya_error:{type(exc).__name__}", started=started
            )
        if all(answer.accepted is True for answer in result.answers.values()):
            return result
        if not self.fallback_to_jev:
            return result
        if any(answer.accepted is False for answer in result.answers.values()):
            reason = "laya_below_provider_threshold"
        else:
            reason = "laya_threshold_unconfigured"
        return await self._fallback(state, questions, reason=reason, started=started)

    async def _fallback(
        self,
        state: str | Mapping[str, Any],
        questions: Mapping[str, DecisionQuestion],
        *,
        reason: str,
        started: float,
    ) -> DecisionResult:
        try:
            result = await self.jev.evaluate(state, questions)
        except Exception as exc:
            emit_telemetry(
                self.telemetry,
                DecisionTelemetryEvent(
                    provider=self.name,
                    operation="fallback",
                    outcome="failed",
                    elapsed_ms=(time.perf_counter() - started) * 1000,
                    question_kinds=tuple(sorted({q.kind.value for q in questions.values()})),
                    error_type=type(exc).__name__,
                    fallback_from="laya",
                    fallback_to="jev",
                    fallback_reason=reason,
                    **correlation_fields(state),
                ),
            )
            raise
        emit_telemetry(
            self.telemetry,
            DecisionTelemetryEvent(
                provider=self.name,
                operation="fallback",
                outcome="succeeded",
                elapsed_ms=(time.perf_counter() - started) * 1000,
                model=result.model,
                question_kinds=tuple(sorted({q.kind.value for q in questions.values()})),
                fallback_from="laya",
                fallback_to="jev",
                fallback_reason=reason,
                **correlation_fields(state),
            ),
        )
        return replace(result, fallback_from="laya", fallback_reason=reason)
