"""Local HTTP Laya provider with bounded requests and explicit health checks."""

from __future__ import annotations

import asyncio
import json
import os
import time
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
    emit_telemetry,
)
from browser_agent.decisions.calibration import CalibrationPolicy

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
        if not questions:
            raise ValueError("at least one decision question is required")
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
        started = time.perf_counter()
        try:
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
            self._emit_call(questions, started, "timeout", error)
            raise error from exc
        except DecisionProviderError as exc:
            self._emit_call(questions, started, "error", exc)
            raise
        except Exception as exc:
            error = DecisionProviderProtocolError(
                f"Laya decision failed with {type(exc).__name__}."
            )
            self._emit_call(questions, started, "error", error)
            raise error from exc

        self._emit_call(questions, started, "success")
        return DecisionResult(
            provider=self.name,
            model=str(get_value(response, "model", "laya-local")),
            answers=normalized,
            calibration_id=self.calibration_id,
        )

    def _emit_call(
        self,
        questions: Mapping[str, DecisionQuestion],
        started: float,
        outcome: str,
        error: DecisionProviderError | None = None,
    ) -> None:
        emit_telemetry(
            self.telemetry,
            DecisionTelemetryEvent(
                provider=self.name,
                operation="evaluate",
                outcome=outcome,
                elapsed_ms=(time.perf_counter() - started) * 1000,
                question_kinds=tuple(
                    sorted({question.kind.value for question in questions.values()})
                ),
                error_type=None if error is None else type(error).__name__,
            ),
        )
