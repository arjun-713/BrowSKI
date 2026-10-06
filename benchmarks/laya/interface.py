"""Prompt variants and recording transport for the Laya decision interface."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable, Mapping
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from browser_agent.decisions.base import DecisionKind, DecisionQuestion
from browser_agent.decisions.laya import JsonTransport, LayaProvider

from .schema import BenchmarkCase, Candidate

JsonResponse = Mapping[str, Any]
RawTransport = Callable[
    [str, str, Mapping[str, Any] | None, float, Mapping[str, str]],
    tuple[JsonResponse, str, Mapping[str, Any]] | tuple[JsonResponse, str],
]


def live_recording_transport(
    method: str,
    url: str,
    payload: Mapping[str, Any] | None,
    timeout: float,
    headers: Mapping[str, str],
) -> tuple[JsonResponse, str, Mapping[str, Any]]:
    """Issue one HTTP request and return its parsed object plus exact response body text."""
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(url, data=body, headers=dict(headers), method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            raw_bytes = response.read()
            status = response.status
            response_headers = dict(response.headers.items())
    except HTTPError as error:
        raw_bytes = error.read()
        status = error.code
        response_headers = dict(error.headers.items()) if error.headers else {}
    raw_text = raw_bytes.decode("utf-8", errors="strict")
    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError:
        parsed = {"_transport_error": "response body was not valid JSON"}
    if not isinstance(parsed, Mapping):
        parsed = {"_transport_error": "response body was not a JSON object"}
    return parsed, raw_text, {"status": status, "headers": response_headers}


class RecordingJsonTransport:
    """Adapt an injected Laya JsonTransport while retaining request/response evidence.

    `raw_transport` returns (parsed_response, raw_http_body). For test fakes the raw
    body should be a literal JSON string. Production runs use live_recording_transport.
    """

    def __init__(self, raw_transport: RawTransport) -> None:
        self.raw_transport = raw_transport
        self.last_request: dict[str, Any] | None = None
        self.last_response: dict[str, Any] | None = None
        self.last_response_raw: str | None = None
        self.last_status: int | None = None
        self.last_headers: dict[str, Any] | None = None
        self.last_timestamp_utc: str | None = None
        self.last_error: dict[str, str] | None = None
        self.elapsed_ms: float | None = None

    def __call__(
        self,
        method: str,
        url: str,
        payload: Mapping[str, Any] | None,
        timeout: float,
        headers: Mapping[str, str],
    ) -> JsonResponse:
        self.last_request = {
            "method": method,
            "url": url,
            "payload": payload,
            "timeout_seconds": timeout,
        }
        self.last_response = None
        self.last_response_raw = None
        self.last_status = None
        self.last_headers = None
        self.last_error = None
        started = time.perf_counter()
        from datetime import datetime, timezone

        self.last_timestamp_utc = datetime.now(timezone.utc).isoformat()
        try:
            transport_result = self.raw_transport(
                method, url, payload, timeout, headers
            )
            response, raw = transport_result[0], transport_result[1]
            metadata = transport_result[2] if len(transport_result) == 3 else {}
            self.last_response = dict(response)
            self.last_response_raw = raw
            self.last_status = (
                metadata.get("status")
                if isinstance(metadata.get("status"), int)
                else None
            )
            response_headers = metadata.get("headers", {})
            self.last_headers = (
                dict(response_headers) if isinstance(response_headers, Mapping) else {}
            )
            self.last_error = None
        except Exception as exc:
            self.last_error = {"type": type(exc).__name__, "message": str(exc)}
            raise
        finally:
            self.elapsed_ms = (time.perf_counter() - started) * 1000
        return response

    @classmethod
    def from_json_transport(cls, transport: JsonTransport) -> RecordingJsonTransport:
        """Wrap a conventional mapping-only transport; raw body is canonical JSON."""

        def wrapped(
            method: str,
            url: str,
            payload: Mapping[str, Any] | None,
            timeout: float,
            headers: Mapping[str, str],
        ) -> tuple[JsonResponse, str, Mapping[str, Any]]:
            response = transport(method, url, payload, timeout, headers)
            return (
                response,
                json.dumps(response, ensure_ascii=False, separators=(",", ":")),
                {},
            )

        return cls(wrapped)


def _elements(
    case: BenchmarkCase, *, include_noise: bool = False
) -> list[dict[str, Any]]:
    elements = list(case.browser_state.elements)
    if include_noise:
        elements.extend(case.browser_state.noise_elements)
    actionable_roles = {
        "button",
        "link",
        "textbox",
        "searchbox",
        "combobox",
        "checkbox",
        "radio",
        "switch",
        "text input",
    }
    return [
        {
            "ref": element.ref or element.semantic_id,
            "role": element.role,
            "name": element.name,
            "text": element.text,
            "state": element.state
            if isinstance(element.state, list)
            else ([element.state] if element.state else []),
            "interactable": element.interactable
            if element.interactable is not None
            else element.role.lower() in actionable_roles,
        }
        for element in elements
    ]


def _baseline_context(
    case: BenchmarkCase, candidates: list[Candidate]
) -> tuple[dict[str, Any], str]:
    """Mirror select_action_candidate state and instruction construction."""
    if case.question_type != "choice":
        state = {
            "task": case.task,
            "current_subgoal": case.current_subgoal,
            "question": case.question,
            "constraints": case.constraints,
            "recent_action": case.recent_action,
            "recent_outcome": case.recent_outcome,
            "relevant_delta": case.relevant_delta,
            "observation": {
                "url": case.browser_state.url,
                "title": case.browser_state.page,
                "state_generation": case.browser_state.state_generation,
                "elements": _elements(case, include_noise=True),
            },
        }
        return state, _typed_prompt(case)

    state = {
        "task": case.task,
        "current_subgoal": case.current_subgoal,
        "run_id": None,
        "steps_taken": None,
        "observation": {
            "url": case.browser_state.url,
            "title": case.browser_state.page,
            "state_generation": case.browser_state.state_generation,
            "elements": _elements(case, include_noise=True),
        },
        "candidates": [
            {"id": f"c{index:02d}", "description": candidate.description}
            for index, candidate in enumerate(candidates, 1)
        ],
    }
    prompt = (
        f"Question: {case.question}\nTask: {case.task}\nCurrent subgoal: {case.current_subgoal}\n"
        "Choose the single supplied candidate that best advances the current subgoal. "
        "Return only one candidate id; do not invent browser actions."
    )
    return state, prompt


def _tuned_context(
    case: BenchmarkCase, candidates: list[Candidate]
) -> tuple[dict[str, Any], str]:
    """Benchmark-only concise, structured context with complete candidate descriptions."""
    state = {
        "task": case.task,
        "current_subgoal": case.current_subgoal,
        "constraints": case.constraints,
        "relevant_elements": _elements(case),
        "recent_action": case.recent_action,
        "recent_outcome": case.recent_outcome,
        "relevant_delta": case.relevant_delta,
        "candidates": [
            {"id": f"c{index:02d}", "description": candidate.description}
            for index, candidate in enumerate(candidates, 1)
        ],
    }
    prompt = _typed_prompt(case, tuned=True)
    return state, prompt


def _typed_prompt(case: BenchmarkCase, *, tuned: bool = False) -> str:
    if case.question_type == "choice":
        if tuned:
            return (
                f"Question: {case.question}\n"
                "Choose exactly one supplied candidate for the immediate next action. "
                "Respect all constraints and prerequisite order. If required evidence is missing, "
                "unsafe, or no candidate is justified, choose the escalation candidate. "
                "Do not invent or combine actions; return only its candidate id."
            )
        return (
            f"Question: {case.question}\nTask: {case.task}\nCurrent subgoal: {case.current_subgoal}\n"
            "Choose the single supplied candidate that best advances the current subgoal. "
            "Return only one candidate id; do not invent browser actions."
        )
    if case.question_type == "score":
        return (
            f"Question: {case.question}\n"
            "Score the specific proposal described in the supplied task context using the "
            "provided criteria. If no proposal is described, do not assume one; use the lowest "
            "applicable score or indicate insufficient evidence."
        )
    return (
        f"Question: {case.question}\n"
        "Answer yes or no using only the supplied current browser evidence. "
        "Do not infer an action or outcome that is not observed."
    )


def make_question(case: BenchmarkCase, candidates: list[Candidate]) -> DecisionQuestion:
    if case.question_type == "choice":
        options = {
            f"c{index:02d}": candidate.description
            for index, candidate in enumerate(candidates, 1)
        }
        return DecisionQuestion(DecisionKind.CHOICE, case.question, options)
    if case.question_type == "score":
        labels = case.criteria
        rubric = (
            tuple(labels)
            if isinstance(labels, list)
            else tuple(f"{key}: {value}" for key, value in (labels or {}).items())
        )
        return DecisionQuestion(DecisionKind.SCORE, case.question, rubric)
    return DecisionQuestion(DecisionKind.NOUL, case.question)


async def evaluate_case(
    provider: LayaProvider,
    recorder: RecordingJsonTransport,
    case: BenchmarkCase,
    *,
    variant: str,
    candidates: list[Candidate] | None = None,
) -> dict[str, Any]:
    candidates = list(candidates if candidates is not None else case.candidates)
    if variant == "baseline":
        state, instructions = _baseline_context(case, candidates)
    elif variant == "tuned":
        state, instructions = _tuned_context(case, candidates)
    else:
        raise ValueError(f"unknown prompt variant: {variant}")
    question = make_question(case, candidates)
    question = DecisionQuestion(question.kind, instructions, question.criteria)
    started = time.perf_counter()
    result = await provider.evaluate(state, {"decision": question})
    answer = result.answers["decision"]
    raw_answer = answer.raw or {}
    candidate_ids = {
        f"c{index:02d}": candidate.semantic_id
        for index, candidate in enumerate(candidates, 1)
    }
    actual_answer = candidate_ids.get(str(answer.value), answer.value)
    raw_probabilities = raw_answer.get("probabilities", {})
    if case.question_type == "choice" and isinstance(raw_probabilities, Mapping):
        raw_probabilities = {
            candidate_ids.get(str(key), str(key)): value
            for key, value in raw_probabilities.items()
        }
    elif case.question_type == "noul":
        yes_probability = float(answer.value)
        raw_probabilities = {"yes": yes_probability, "no": 1.0 - yes_probability}
    probability_values = (
        sorted((float(value) for value in raw_probabilities.values()), reverse=True)
        if isinstance(raw_probabilities, Mapping)
        else []
    )
    chosen_confidence = _number(raw_answer.get("answer_confidence"))
    if (
        chosen_confidence is None
        and isinstance(raw_probabilities, Mapping)
        and raw_probabilities
    ):
        chosen_confidence = max(float(value) for value in raw_probabilities.values())
    if case.question_type == "noul":
        chosen_confidence = max(float(answer.value), 1.0 - float(answer.value))
    elif (
        case.question_type == "score"
        and isinstance(raw_probabilities, Mapping)
        and raw_probabilities
    ):
        chosen_confidence = max(float(value) for value in raw_probabilities.values())
    return {
        "case_id": case.case_id,
        "category": case.category,
        "question_type": case.question_type,
        "variant": variant,
        "candidate_order": [candidate.semantic_id for candidate in candidates]
        if case.question_type == "choice"
        else [],
        "request": recorder.last_request,
        "response_raw": recorder.last_response_raw,
        "response_status": recorder.last_status,
        "response_headers": recorder.last_headers,
        "timestamp_utc": recorder.last_timestamp_utc,
        "response": recorder.last_response,
        "model": result.model,
        "routing": recorder.last_response.get("routing")
        if recorder.last_response
        else None,
        "answer": actual_answer,
        "answer_provider_id": answer.value if case.question_type == "choice" else None,
        "probabilities": dict(answer.probabilities),
        "raw_probabilities": raw_probabilities,
        "top1_probability": probability_values[0] if probability_values else None,
        "top2_probability": probability_values[1]
        if len(probability_values) > 1
        else None,
        "probability_margin": probability_values[0] - probability_values[1]
        if len(probability_values) > 1
        else None,
        "confidence": _number(raw_answer.get("confidence")),
        "answer_confidence": _number(raw_answer.get("answer_confidence")),
        "normalized_confidence": answer.confidence_raw,
        "provider_accepted": answer.accepted,
        "chosen_answer_confidence": chosen_confidence,
        "noul_p_yes": float(answer.value) if case.question_type == "noul" else None,
        "usage": recorder.last_response.get("usage")
        if recorder.last_response
        else None,
        "latency_ms": recorder.elapsed_ms or (time.perf_counter() - started) * 1000,
        "calibration_id": result.calibration_id,
    }


def _number(value: Any) -> float | None:
    return (
        float(value)
        if isinstance(value, (int, float)) and not isinstance(value, bool)
        else None
    )


def sync_evaluate(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return asyncio.run(evaluate_case(*args, **kwargs))
