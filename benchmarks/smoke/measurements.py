"""Extract comparable provider and Rust action metrics from debug JSONL."""

from __future__ import annotations

import json
from pathlib import Path


def read_event_metrics(path: Path) -> dict[str, object]:
    """Count wire calls and retain provider latency, usage, and Rust timings."""
    requests: dict[str, dict[str, object]] = {}
    responses: dict[str, dict[str, object]] = {}
    actions: list[dict[str, object]] = []
    if not path.is_file():
        return {
            "provider_call_count": 0,
            "provider_calls": [],
            "usage_totals": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
            "rust_action_timings": [],
        }

    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        name = event.get("event")
        payload = event.get("payload")
        if not isinstance(payload, dict):
            continue
        if name == "provider.request":
            call_id = payload.get("call_id")
            if isinstance(call_id, str):
                requests[call_id] = {
                    "provider": payload.get("provider"),
                    "operation": payload.get("operation"),
                    "model": payload.get("model"),
                }
        elif name == "provider.response":
            call_id = payload.get("call_id")
            if isinstance(call_id, str):
                response = payload.get("response")
                usage = response.get("usage") if isinstance(response, dict) else None
                responses[call_id] = {
                    "elapsed_ms": payload.get("elapsed_ms"),
                    "usage": usage if isinstance(usage, dict) else None,
                }
        elif name == "browser.action_result":
            outcome = payload.get("outcome")
            if isinstance(outcome, dict):
                timings = outcome.get("timings")
                if isinstance(timings, dict):
                    verification = outcome.get("verification")
                    actions.append(
                        {
                            "elapsed_ms": outcome.get("elapsed_ms"),
                            "verification": (
                                verification.get("status")
                                if isinstance(verification, dict)
                                else None
                            ),
                            "timings": timings,
                        }
                    )

    calls: list[dict[str, object]] = []
    for call_id, request in requests.items():
        response = responses.get(call_id, {})
        calls.append({"request": request, **response, "responded": bool(response)})
    usage_totals = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    for call in calls:
        usage = call.get("usage")
        if isinstance(usage, dict):
            for name in usage_totals:
                count = usage.get(name)
                if isinstance(count, int):
                    usage_totals[name] += count
    return {
        "provider_call_count": len(calls),
        "provider_calls": calls,
        "usage_totals": usage_totals,
        "rust_action_timings": actions,
    }
