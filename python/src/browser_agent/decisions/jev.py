"""Optional TypeSafe Jev cloud implementation of the shared decision contract."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, cast

from browser_agent.decisions._normalize import get_value, normalize_answer
from browser_agent.decisions.base import (
    DecisionKind,
    DecisionProvider,
    DecisionProviderError,
    DecisionProviderProtocolError,
    DecisionProviderTimeout,
    DecisionProviderUnavailable,
    DecisionQuestion,
    DecisionResult,
    DecisionTelemetry,
    DecisionTelemetryEvent,
    correlation_fields,
    emit_telemetry,
    response_model_name,
    response_usage_counts,
)
from browser_agent.decisions.calibration import CalibrationPolicy


class JevProvider(DecisionProvider):
    name = "jev"

    def __init__(
        self,
        client: Any | None = None,
        *,
        timeout_ms: int = 10_000,
        calibration: CalibrationPolicy | None = None,
        calibration_id: str | None = None,
        telemetry: DecisionTelemetry | None = None,
    ) -> None:
        if timeout_ms <= 0:
            raise ValueError("Jev timeout must be greater than zero")
        self.timeout_ms = timeout_ms
        self.calibration = calibration or CalibrationPolicy()
        self.calibration_id = calibration_id or self.calibration.calibration_id
        self._client: Any | None = client
        self._owns_client = client is None
        self.telemetry = telemetry

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                from typesafe_sdk import AsyncTypeSafeClient  # type: ignore[import-not-found]
            except ImportError as exc:  # pragma: no cover - depends on optional extra
                raise DecisionProviderUnavailable(
                    'JevProvider requires the "decisions-cloud" extra: '
                    'pip install "browser-agent[decisions-cloud]"'
                ) from exc
            self._client = cast(Any, AsyncTypeSafeClient())
        return self._client

    async def evaluate(
        self, state: str | Mapping[str, Any], questions: Mapping[str, DecisionQuestion]
    ) -> DecisionResult:
        if not questions:
            raise ValueError("at least one decision question is required")
        try:
            from typesafe_sdk import Choice, Noul, Score  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - depends on optional extra
            raise DecisionProviderUnavailable(
                'JevProvider requires the "decisions-cloud" extra: '
                'pip install "browser-agent[decisions-cloud]"'
            ) from exc

        sdk_questions: dict[str, Any] = {}
        for name, question in questions.items():
            if question.kind == DecisionKind.CHOICE:
                sdk_questions[name] = Choice(
                    instructions=question.instructions, criteria=question.criteria
                )
            elif question.kind == DecisionKind.SCORE:
                sdk_questions[name] = Score(
                    instructions=question.instructions, criteria=list(question.criteria or ())
                )
            else:
                sdk_questions[name] = Noul(instructions=question.instructions)

        started = time.perf_counter()
        try:
            async with asyncio.timeout(self.timeout_ms / 1000):
                response = await self._get_client().system_one(state=state, questions=sdk_questions)
            normalized: dict[str, Any] = {}
            for name, question in questions.items():
                if question.kind == DecisionKind.CHOICE:
                    raw = response.choices[name]
                elif question.kind == DecisionKind.SCORE:
                    raw = response.scores[name]
                else:
                    raw = response.nouls[name]
                normalized[name] = normalize_answer(question.kind, raw, question, self.calibration)
        except TimeoutError as exc:
            error = DecisionProviderTimeout("Jev request exceeded its configured timeout.")
            self._emit_call(questions, started, "timeout", error, state=state)
            raise error from exc
        except DecisionProviderError as exc:
            self._emit_call(questions, started, "error", exc, state=state)
            raise
        except (KeyError, AttributeError, TypeError) as exc:
            error = DecisionProviderProtocolError("Jev response omitted typed answers.")
            self._emit_call(questions, started, "error", error, state=state)
            raise error from exc
        except Exception as exc:
            error = DecisionProviderUnavailable(f"Jev request failed with {type(exc).__name__}.")
            self._emit_call(questions, started, "error", error, state=state)
            raise error from exc

        self._emit_call(questions, started, "success", response=response, state=state)
        return DecisionResult(
            provider=self.name,
            model=str(get_value(response, "model", "jev-latest")),
            answers=normalized,
            calibration_id=self.calibration_id,
        )

    async def aclose(self) -> None:
        """Close an SDK client created by this provider, leaving injected clients alone."""
        if not self._owns_client or self._client is None:
            return
        close = getattr(self._client, "aclose", None)
        if callable(close):
            await cast(Callable[[], Awaitable[Any]], close)()
        self._client = None

    def _emit_call(
        self,
        questions: Mapping[str, DecisionQuestion],
        started: float,
        outcome: str,
        error: DecisionProviderError | None = None,
        *,
        response: object | None = None,
        state: str | Mapping[str, Any],
    ) -> None:
        input_tokens, output_tokens = response_usage_counts(response)
        emit_telemetry(
            self.telemetry,
            DecisionTelemetryEvent(
                provider=self.name,
                operation="evaluate",
                outcome=outcome,
                elapsed_ms=(time.perf_counter() - started) * 1000,
                model=response_model_name(response, "jev-latest"),
                question_kinds=tuple(sorted({q.kind.value for q in questions.values()})),
                error_type=None if error is None else type(error).__name__,
                **correlation_fields(state),
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            ),
        )
