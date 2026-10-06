"""Capture the installed Laya API contract with three small CPU requests."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import platform
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _installed_laya_version(laya_python: Path | None) -> str:
    if laya_python is None:
        return importlib.metadata.version("laya")

    output = subprocess.check_output(
        [
            str(laya_python),
            "-c",
            "import importlib.metadata as m; print(m.version('laya'))",
        ],
        text=True,
    )
    return output.strip()


def _request(
    endpoint: str,
    method: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    body = None if payload is None else json.dumps(payload).encode()
    headers = {} if body is None else {"Content-Type": "application/json"}
    request = Request(
        endpoint,
        data=body,
        headers=headers,
        method=method,
    )
    started = time.perf_counter()
    try:
        with urlopen(request, timeout=90) as response:
            raw_body = response.read().decode()
            status = response.status
            response_headers = dict(response.headers.items())
    except HTTPError as error:
        raw_body = error.read().decode(errors="replace")
        status = error.code
        response_headers = dict(error.headers.items())

    elapsed_ms = (time.perf_counter() - started) * 1000
    try:
        parsed_body: Any = json.loads(raw_body)
    except json.JSONDecodeError:
        parsed_body = None

    return {
        "timestamp_utc": _utc_now(),
        "endpoint": endpoint,
        "http_status": status,
        "request": payload,
        "response_headers": response_headers,
        "response_raw": raw_body,
        "response": parsed_body,
        "latency_ms_client_wall": round(elapsed_ms, 3),
    }


def _choice_probe() -> dict[str, Any]:
    return {
        "state": {
            "task": "Search jobs for AI internships in Bengaluru.",
            "current_subgoal": "Apply the location filter before searching.",
            "page": "Jobs Search",
            "relevant_elements": [
                {"ref": "@keywords", "role": "textbox", "value": "AI internship"},
                {"ref": "@location", "role": "textbox", "value": ""},
                {"ref": "@search", "role": "button", "text": "Search"},
            ],
            "constraints": ["Location must be Bengaluru."],
        },
        "questions": {
            "next_action": {
                "type": "choice",
                "instructions": (
                    "Choose the single best immediate action. Do not skip the "
                    "location prerequisite."
                ),
                "criteria": {
                    "A": "Type Bengaluru into @location.",
                    "B": "Click @search before setting the location.",
                    "ESCALATE_TO_REASONER": (
                        "Escalate because the available state is insufficient."
                    ),
                },
            }
        },
    }


def _score_probe() -> dict[str, Any]:
    return {
        "state": {
            "task": "Submit the application and verify it was accepted.",
            "current_subgoal": "Judge whether the application has been verified.",
            "page": "Application confirmation",
            "relevant_elements": [
                {
                    "ref": "@notice",
                    "role": "status",
                    "text": "Application submitted successfully.",
                },
                {
                    "ref": "@application_id",
                    "role": "text",
                    "text": "Application ID: A-2048",
                },
            ],
            "recent_verified_action": "Clicked @submit.",
        },
        "questions": {
            "completion_evidence": {
                "type": "score",
                "instructions": "Score the evidence that the application was accepted.",
                "criteria": [
                    "0: no evidence of acceptance",
                    "1: weak or ambiguous evidence",
                    "2: explicit confirmation only",
                    "3: explicit confirmation and record ID",
                ],
            }
        },
    }


def _noul_probe() -> dict[str, Any]:
    return {
        "state": {
            "task": "Confirm the application was accepted.",
            "current_subgoal": "Determine whether the current state proves acceptance.",
            "page": "Application confirmation",
            "relevant_elements": [
                {
                    "ref": "@notice",
                    "role": "status",
                    "text": "Application submitted successfully.",
                },
                {
                    "ref": "@application_id",
                    "role": "text",
                    "text": "Application ID: A-2048",
                },
            ],
        },
        "questions": {
            "accepted": {
                "type": "noul",
                "instructions": (
                    "Does the current browser evidence explicitly prove that the "
                    "application was accepted? Answer yes or no."
                ),
            }
        },
    }


def _record_probe(
    endpoint: str,
    case_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    record = _request(f"{endpoint}/v1/systemone", "POST", payload)
    record["record_type"] = "decision_probe"
    record["case_id"] = case_id
    response = record.get("response")
    if isinstance(response, dict):
        answers = response.get("answers", {})
        record["parsed"] = {
            "model": response.get("model"),
            "routing_model": response.get("routing", {}).get("model")
            if isinstance(response.get("routing"), dict)
            else None,
            "answers": answers,
            "usage": response.get("usage"),
            "routing": response.get("routing"),
        }
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", default="http://127.0.0.1:8000")
    parser.add_argument("--laya-python", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).parent,
    )
    args = parser.parse_args()

    endpoint = args.endpoint.rstrip("/")
    output_dir = args.output
    output_dir.mkdir(parents=True, exist_ok=True)

    health_record = _request(f"{endpoint}/health", "GET")
    health_record["record_type"] = "health"
    if health_record["http_status"] != 200:
        print(json.dumps(health_record, ensure_ascii=False, indent=2))
        return 1

    health = health_record.get("response")
    if not isinstance(health, dict):
        print(json.dumps(health_record, ensure_ascii=False, indent=2))
        return 1

    probes = [
        ("phase-a-choice", _choice_probe()),
        ("phase-a-score", _score_probe()),
        ("phase-a-noul", _noul_probe()),
    ]
    records = [health_record]
    for case_id, payload in probes:
        record = _record_probe(endpoint, case_id, payload)
        records.append(record)
        if record["http_status"] != 200:
            print(json.dumps(record, ensure_ascii=False, indent=2))
            return 1

    environment = {
        "captured_at_utc": _utc_now(),
        "laya_package_version": _installed_laya_version(args.laya_python),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "service_endpoint": endpoint,
        "model": records[1]["parsed"].get("model"),
        "routing_model": records[1]["parsed"].get("routing_model"),
        "health": health,
        "checkpoint_revision": health.get("revisions"),
        "device": health.get("device"),
        "openapi": "3.1.0",
        "systemone_paths": ["/v1/systemone", "/v1/systemone/batch"],
        "warning_observed": (
            "The English checkpoint temperature for choice:11+ was outside "
            "the supported range and clamped to 0.5; its confidence is uncalibrated."
        ),
    }

    (output_dir / "environment.json").write_text(
        json.dumps(environment, ensure_ascii=False, indent=2) + "\n"
    )
    with (output_dir / "probes.jsonl").open("w") as output_file:
        for record in records:
            output_file.write(
                json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
            )

    print(
        json.dumps(
            {
                "environment": str(output_dir / "environment.json"),
                "probes": str(output_dir / "probes.jsonl"),
                "records": len(records),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
