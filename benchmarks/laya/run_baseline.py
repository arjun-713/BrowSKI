"""Run reproducible Laya benchmark variants and preserve request/response evidence."""

from __future__ import annotations

import argparse
import asyncio
import json
import random
from pathlib import Path
from typing import Any

from browser_agent.decisions.laya import LayaProvider

from .interface import RecordingJsonTransport, evaluate_case, live_recording_transport
from .schema import BenchmarkCase, load_cases


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="Gold JSONL fixture")
    parser.add_argument(
        "--output", type=Path, required=True, help="Append-only raw JSONL output"
    )
    parser.add_argument(
        "--checkpoint", type=Path, required=True, help="Resume checkpoint JSONL"
    )
    parser.add_argument("--endpoint", default="http://127.0.0.1:8000")
    parser.add_argument("--seed", type=int, default=20261006)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--variant", choices=("baseline", "tuned"), default="baseline")
    parser.add_argument(
        "--analysis", type=Path, help="Required analysis report before tuned runs"
    )
    parser.add_argument("--timeout-ms", type=int, default=90_000)
    parser.add_argument(
        "--offline-responses", type=Path, help="Replay raw HTTP responses from JSONL"
    )
    return parser


def _replay_transport(path: Path):
    records: list[tuple[dict[str, Any], str, dict[str, Any]]] = []
    with path.open(encoding="utf-8") as source:
        for line in source:
            if line.strip():
                row = json.loads(line)
                records.append(
                    (
                        row["response"],
                        row["response_raw"],
                        {
                            "status": row.get("response_status"),
                            "headers": row.get("response_headers", {}),
                        },
                    )
                )
    cursor = 0

    def transport(method, url, payload, timeout, headers):
        nonlocal cursor
        if method != "POST":
            raise ValueError("offline replay supports only decision POST calls")
        if cursor >= len(records):
            raise RuntimeError("offline replay responses exhausted")
        response, raw, metadata = records[cursor]
        cursor += 1
        return response, raw, metadata

    return transport


def _position_orders(case: BenchmarkCase, seed: int) -> list[tuple[int, list[Any]]]:
    canonical = list(case.candidates)
    if not case.position_probe:
        return []
    if len(canonical) < 2:
        return []
    reverse = list(reversed(canonical))
    left = canonical[1:] + canonical[:1]
    right = canonical[-1:] + canonical[:-1]
    orders = [(1, reverse), (2, left), (3, right)]
    random.Random(f"{seed}:{case.case_id}").shuffle(orders)
    return orders


async def _run(args: argparse.Namespace) -> int:
    cases = load_cases(args.input)
    if args.repeats != 3:
        raise ValueError("benchmark protocol requires exactly three repeats")
    if args.variant == "tuned":
        if args.analysis is None or not args.analysis.is_file():
            raise ValueError(
                "tuned runs require --analysis from the completed baseline evaluation"
            )
        report = json.loads(args.analysis.read_text(encoding="utf-8"))
        baseline_path = report.get("source_results")
        if not baseline_path or not Path(baseline_path).is_file():
            raise ValueError(
                "analysis report must identify an existing source_results baseline file"
            )

    completed: set[tuple[str, int, str, int]] = set()
    max_run_index = 0
    for source in (args.checkpoint, args.output):
        if source.exists():
            with source.open(encoding="utf-8") as rows:
                for line in rows:
                    if line.strip():
                        row = json.loads(line)
                        completed.add(
                            (
                                row["case_id"],
                                row["repeat"],
                                row["variant"],
                                row.get("permutation_index", 0),
                            )
                        )
                        max_run_index = max(max_run_index, int(row.get("run_index", 0)))

    raw_transport = (
        _replay_transport(args.offline_responses)
        if args.offline_responses
        else live_recording_transport
    )
    recorder = RecordingJsonTransport(raw_transport)
    provider = LayaProvider(
        endpoint_url=args.endpoint,
        timeout_ms=args.timeout_ms,
        transport=recorder,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.checkpoint.parent.mkdir(parents=True, exist_ok=True)
    run_index = max_run_index
    with (
        args.output.open("a", encoding="utf-8") as output,
        args.checkpoint.open("a", encoding="utf-8") as checkpoint,
    ):
        for case in cases:
            for repeat in range(1, 4):
                jobs = [(0, list(case.candidates))]
                if repeat == 3:
                    jobs.extend(_position_orders(case, args.seed))
                for permutation_index, candidates in jobs:
                    repeat_record = 0 if permutation_index else repeat
                    key = (case.case_id, repeat_record, args.variant, permutation_index)
                    if key in completed:
                        continue
                    run_index += 1
                    try:
                        result = await evaluate_case(
                            provider,
                            recorder,
                            case,
                            variant=args.variant,
                            candidates=candidates,
                        )
                    except Exception as exc:  # noqa: BLE001 - persist every failed transport/provider call
                        result = {
                            "case_id": case.case_id,
                            "category": case.category,
                            "question_type": case.question_type,
                            "variant": args.variant,
                            "request": recorder.last_request,
                            "response_raw": recorder.last_response_raw,
                            "response": recorder.last_response,
                            "response_status": recorder.last_status,
                            "response_headers": recorder.last_headers,
                            "routing": recorder.last_response.get("routing")
                            if recorder.last_response
                            else None,
                            "timestamp_utc": recorder.last_timestamp_utc,
                            "latency_ms": recorder.elapsed_ms,
                            "error": recorder.last_error
                            or {"type": type(exc).__name__, "message": str(exc)},
                        }
                    result.update(
                        {
                            "repeat": repeat_record,
                            "permutation_index": permutation_index,
                            "run_index": run_index,
                            "seed": args.seed,
                            "analysis_report": str(args.analysis)
                            if args.analysis
                            else None,
                        }
                    )
                    encoded = (
                        json.dumps(result, ensure_ascii=False, separators=(",", ":"))
                        + "\n"
                    )
                    output.write(encoded)
                    output.flush()
                    checkpoint.write(encoded)
                    checkpoint.flush()
                    print(
                        f"{case.case_id} repeat={repeat} permutation={permutation_index} variant={args.variant}: recorded"
                    )
    return 0


def main() -> int:
    return asyncio.run(_run(_parser().parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
