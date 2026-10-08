"""Local HTTP Laya provider with bounded requests and explicit health checks."""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from collections.abc import Callable, Mapping
from typing import Any, cast
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

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
    ProviderHealth,
    correlation_fields,
    emit_telemetry,
    response_model_name,
    response_usage_counts,
)
from browser_agent.decisions.calibration import CalibrationPolicy
from browser_agent.telemetry.debug_log import record_debug

JsonTransport = Callable[
    [str, str, Mapping[str, Any] | None, float, Mapping[str, str]], Mapping[str, Any]
]


def _request_json(
    method: str,
    url: str,
    payload: Mapping[str, Any] | None,
    timeout_seconds: float,
    headers: Mapping[str, str],
) -> Mapping[str, Any]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(url, data=data, headers=dict(headers), method=method)
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            body = response.read()
    except HTTPError as exc:
        raise DecisionProviderUnavailable(f"Laya endpoint returned HTTP {exc.code}.") from exc
    except TimeoutError as exc:
        raise DecisionProviderTimeout("Laya endpoint request timed out.") from exc
    except URLError as exc:
        if isinstance(exc.reason, TimeoutError):
            raise DecisionProviderTimeout("Laya endpoint request timed out.") from exc
        raise DecisionProviderUnavailable("Laya endpoint could not be reached.") from exc

    try:
        decoded = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DecisionProviderProtocolError("Laya endpoint returned invalid JSON.") from exc
    if not isinstance(decoded, Mapping):
        raise DecisionProviderProtocolError("Laya endpoint returned a non-object response.")
    return cast(Mapping[str, Any], decoded)


class LayaProvider(DecisionProvider):
    """Call a separately managed local Laya service; never download weights here."""

    name = "laya"

    def __init__(
        self,
        model: Any | None = None,
        *,
        endpoint_url: str = "http://127.0.0.1:8000",
        timeout_ms: int = 5_000,
        health_timeout_ms: int = 1_000,
        api_key_env: str = "LAYA_API_KEY",
        calibration: CalibrationPolicy | None = None,
        calibration_id: str | None = None,
        telemetry: DecisionTelemetry | None = None,
        transport: JsonTransport | None = None,
    ) -> None:
        if timeout_ms <= 0 or health_timeout_ms <= 0:
            raise ValueError("Laya timeouts must be greater than zero")
        self.endpoint_url = endpoint_url.rstrip("/")
        self.timeout_ms = timeout_ms
        self.health_timeout_ms = health_timeout_ms
        self.api_key_env = api_key_env
        self.calibration = calibration or CalibrationPolicy()
        self.calibration_id = calibration_id or self.calibration.calibration_id
        self.telemetry = telemetry
        self._transport = transport or _request_json
        self._test_model = model

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        token = os.environ.get(self.api_key_env)
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    async def health_check(self) -> ProviderHealth:
        """Check Laya liveness without loading a model or starting a server."""
        started = time.perf_counter()
        if self._test_model is not None:
            result = ProviderHealth(self.name, available=True, detail="injected model")
            emit_telemetry(
                self.telemetry,
                DecisionTelemetryEvent(self.name, "health", "available", 0.0),
            )
            return result

        try:
            await asyncio.to_thread(
                self._transport,
                "GET",
                f"{self.endpoint_url}/health",
                None,
                self.health_timeout_ms / 1000,
                self._headers(),
            )
        except DecisionProviderError as exc:
            elapsed_ms = (time.perf_counter() - started) * 1000
            emit_telemetry(
                self.telemetry,
                DecisionTelemetryEvent(
                    self.name, "health", "unavailable", elapsed_ms, error_type=type(exc).__name__
                ),
            )
            return ProviderHealth(
                self.name,
                available=False,
                endpoint=self.endpoint_url,
                detail=type(exc).__name__,
            )
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - started) * 1000
            emit_telemetry(
                self.telemetry,
                DecisionTelemetryEvent(
                    self.name, "health", "unavailable", elapsed_ms, error_type=type(exc).__name__
                ),
            )
            return ProviderHealth(
                self.name,
                available=False,
                endpoint=self.endpoint_url,
                detail=type(exc).__name__,
            )

        elapsed_ms = (time.perf_counter() - started) * 1000
        emit_telemetry(
            self.telemetry,
            DecisionTelemetryEvent(self.name, "health", "available", elapsed_ms),
        )
        return ProviderHealth(self.name, available=True, endpoint=self.endpoint_url)

    async def evaluate(
        self, state: str | Mapping[str, Any], questions: Mapping[str, DecisionQuestion]
    ) -> DecisionResult:
        started = time.perf_counter()
        call_id = str(uuid.uuid4())
        if not questions:
            error = ValueError("at least one decision question is required")
            self._record_debug_call(
                "provider.error", call_id, started, error_type=type(error).__name__
            )
            raise error
        payload = {
            name: {
                "type": question.kind.value,
                "instructions": question.instructions,
                **(
                    {
                        "criteria": (
                            {
                                option: description or option
                                for option, description in question.criteria.items()
                            }
                            if question.kind == DecisionKind.CHOICE
                            and isinstance(question.criteria, Mapping)
                            else question.criteria
                        )
                    }
                    if question.criteria is not None
                    else {}
                ),
            }
            for name, question in questions.items()
        }
        response: object | None = None
        try:
            self._record_debug_call(
                "provider.request",
                call_id,
                started,
                request={"state": state, "questions": payload},
            )
            if self._test_model is not None:
                response = await asyncio.wait_for(
                    asyncio.to_thread(self._test_model.predict, state, payload),
                    timeout=self.timeout_ms / 1000,
                )
            else:
                response = await asyncio.wait_for(
                    asyncio.to_thread(
                        self._transport,
                        "POST",
                        f"{self.endpoint_url}/v1/systemone",
                        {"state": state, "questions": payload},
                        self.timeout_ms / 1000,
                        self._headers(),
                    ),
                    timeout=self.timeout_ms / 1000,
                )
            response_mapping: Mapping[str, Any] = {}
            if isinstance(response, Mapping):
                # The transport/test-model seam is intentionally untyped at runtime.
                response_mapping = cast(Mapping[str, Any], response)
            input_tokens, output_tokens = response_usage_counts(cast(object, response))
            self._record_debug_call(
                "provider.response",
                call_id,
                started,
                response=response_mapping,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )
            answers = get_value(response, "answers", {})
            if not isinstance(answers, Mapping):
                raise DecisionProviderProtocolError("Laya response has no answer mapping.")
            normalized = {
                name: normalize_answer(question.kind, answers[name], question, self.calibration)
                for name, question in questions.items()
                if name in answers
            }
            if len(normalized) != len(questions):
                raise DecisionProviderProtocolError("Laya response omitted a requested answer.")
        except TimeoutError as exc:
            error = DecisionProviderTimeout("Laya decision exceeded its configured timeout.")
            self._record_debug_call(
                "provider.error", call_id, started, error_type=type(error).__name__
            )
            self._emit_call(questions, started, "timeout", error, state=state)
            raise error from exc
        except DecisionProviderError as exc:
            self._record_debug_call(
                "provider.error", call_id, started, error_type=type(exc).__name__
            )
            self._emit_call(questions, started, "error", exc, state=state)
            raise
        except Exception as exc:
            error = DecisionProviderProtocolError(
                f"Laya decision failed with {type(exc).__name__}."
            )
            self._record_debug_call(
                "provider.error", call_id, started, error_type=type(error).__name__
            )
            self._emit_call(questions, started, "error", error, state=state)
            raise error from exc

        self._emit_call(questions, started, "success", response=cast(object, response), state=state)
        return DecisionResult(
            provider=self.name,
            model=str(get_value(response, "model", "laya-local")),
            answers=normalized,
            calibration_id=self.calibration_id,
        )

    def _record_debug_call(
        self,
        event: str,
        call_id: str,
        started: float,
        **payload: object,
    ) -> None:
        record_debug(
            event,
            {
                "call_id": call_id,
                "provider": self.name,
                "operation": "evaluate",
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
                **payload,
            },
        )

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
                model=response_model_name(response, "laya-local"),
                question_kinds=tuple(
                    sorted({question.kind.value for question in questions.values()})
                ),
                error_type=None if error is None else type(error).__name__,
                **correlation_fields(state),
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            ),
        )
