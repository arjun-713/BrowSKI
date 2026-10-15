"""Build broad/scoped semantic choices and query the local Laya provider."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from browser_agent.decisions.base import DecisionAnswer
from browser_agent.decisions.laya import LayaProvider

from benchmarks.task_mix.probe_dataset import (
    SCOPED_AUTHORIZATION,
    SCOPED_ESCALATE_DESCRIPTION,
    SCOPED_EXECUTE_SUFFIXES,
    SCOPED_INSTRUCTIONS,
    SCOPED_PREREQUISITES,
)
from benchmarks.task_mix.probe_packets import PERMUTATION_IDS


def _scoped_description(command: dict[str, Any]) -> str:
    label = json.dumps(str(command["label"])[:120], ensure_ascii=True)
    kind = str(command["kind"])
    description = f"{kind} the user-named control {label}"
    description += SCOPED_EXECUTE_SUFFIXES.get(kind, "")
    if kind == "check":
        description += f" to checked={command['checked']}"
    return description


def _broad_request(
    row: dict[str, Any], order: list[str]
) -> tuple[dict[str, Any], str, dict[str, str]]:
    by_id = {
        candidate["candidate_id"]: candidate for candidate in row["broad_candidates"]
    }
    options = {
        candidate_id: by_id[candidate_id]["description"] for candidate_id in order
    }
    state = {
        **row["broad_state"],
        "candidate_actions": [by_id[candidate_id] for candidate_id in order],
        "instruction": (
            "Choose one immediate browser action that best satisfies the user task. "
            "Respect prerequisites, do not guess missing information, and choose "
            "ESCALATE_TO_REASONER when no action is safely justified."
        ),
    }
    return state, state["instruction"], options


def _scoped_request(
    row: dict[str, Any], reverse_options: bool = False
) -> tuple[dict[str, Any], str, dict[str, str]]:
    command = row["scoped_command"]
    if not isinstance(command, dict):
        raise TypeError("out-of-scope cases must never make scoped inference calls")
    state = {
        "run_id": f"laya-probe-{row['case_id']}",
        "steps_taken": 0,
        "user_command": _scoped_description(command),
        "authorization": SCOPED_AUTHORIZATION,
        "prerequisites": SCOPED_PREREQUISITES,
    }
    options = {
        "EXECUTE_AUTHORIZED_COMMAND": state["user_command"],
        "ESCALATE_TO_REASONER": SCOPED_ESCALATE_DESCRIPTION,
    }
    if reverse_options:
        options = dict(reversed(list(options.items())))
    return state, SCOPED_INSTRUCTIONS, options


def _request_variants(row: dict[str, Any], arm: str) -> list[dict[str, Any]]:
    if arm == "broad":
        orders = row["order_permutations"]
        names = PERMUTATION_IDS if row["position_probe"] else ("canonical",)
        return [{"variant": name, "order": orders[name]} for name in names]
    if not row["in_scope"]:
        return []
    variants = [{"variant": "canonical", "reverse_options": False}]
    if row["position_probe"]:
        variants.append({"variant": "reverse", "reverse_options": True})
    return variants


async def _ask(
    provider: LayaProvider,
    endpoint: str,
    row: dict[str, Any],
    arm: str,
    variant: dict[str, Any],
) -> dict[str, Any]:
    if arm == "broad":
        state, instructions, options = _broad_request(row, variant["order"])
    else:
        state, instructions, options = _scoped_request(row, variant["reverse_options"])
    answer: DecisionAnswer = await provider.choose(state, instructions, options)
    recorder = provider._transport
    request_body = getattr(recorder, "last_request", None)
    response_body = getattr(recorder, "last_response", None)
    response = response_body if isinstance(response_body, dict) else {}
    raw_answers = response.get("answers", {})
    raw_answer = (
        raw_answers.get("decision", {}) if isinstance(raw_answers, dict) else {}
    )
    raw_probabilities = (
        raw_answer.get("probabilities", {}) if isinstance(raw_answer, dict) else {}
    )
    if not isinstance(raw_probabilities, dict):
        raw_probabilities = {}
    probability_values = [float(value) for value in raw_probabilities.values()]
    raw_margin = (
        max(probability_values) - sorted(probability_values, reverse=True)[1]
        if len(probability_values) >= 2
        else None
    )
    raw_confidence = (
        raw_answer.get("answer_confidence") if isinstance(raw_answer, dict) else None
    )
    return {
        "record_type": "probe_result",
        "case_id": row["case_id"],
        "family": row["family"],
        "arm": arm,
        "variant": variant["variant"],
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "endpoint": f"{endpoint}/v1/systemone",
        "http_status": getattr(recorder, "last_status", None),
        "latency_ms": getattr(recorder, "elapsed_ms", None),
        "selected": str(answer.value),
        "raw_answer": raw_answer,
        "raw_answer_confidence": raw_confidence,
        "raw_confidence": raw_answer.get("confidence")
        if isinstance(raw_answer, dict)
        else None,
        "raw_probabilities": raw_probabilities,
        "raw_top_margin": raw_margin,
        "normalized_probabilities": answer.probabilities,
        "correct": str(answer.value) == _expected(row, arm),
        "gold_candidate": _expected(row, arm),
        "candidate_order": list(variant.get("order", list(options))),
        "request_payload": request_body.get("payload")
        if isinstance(request_body, dict)
        else None,
        "response_raw": getattr(recorder, "last_response_raw", None),
    }


def _expected(row: dict[str, Any], arm: str) -> str:
    if arm == "broad":
        return str(row["gold_candidate"])
    return "EXECUTE_AUTHORIZED_COMMAND"
