"""Offline descriptive metrics for captured Laya benchmark JSONL records."""

from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

from .calibration import (
    brier_score,
    confidence_buckets,
    expected_calibration_error,
    noul_brier,
    noul_ece,
    noul_probability_buckets,
    top_margin,
)


def load_records(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as source:
        return [json.loads(line) for line in source if line.strip()]


def _gold(case: dict[str, Any]) -> list[Any]:
    return [case.get("expected_answer"), *case.get("acceptable_answers", [])]


def _equivalent(actual: Any, expected: Any) -> bool:
    if actual == expected:
        return True
    if isinstance(actual, bool) or isinstance(expected, bool):
        return str(actual).casefold() == str(expected).casefold()
    try:
        return math.isclose(float(actual), float(expected), abs_tol=1e-6)
    except (TypeError, ValueError):
        return str(actual).strip().casefold() == str(expected).strip().casefold()


def _score_bucket(value: Any) -> int | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    # Rubric scores are non-negative: floor(x + 0.5) is half-up at ties.
    return math.floor(numeric + 0.5)


def is_correct(row: dict[str, Any], case: dict[str, Any]) -> bool:
    actual = row.get("answer")
    if case.get("question_type") == "score":
        actual = _score_bucket(actual)
        return actual is not None and any(
            (expected_bucket := _score_bucket(answer)) is not None
            and actual == expected_bucket
            for answer in _gold(case)
        )
    if case.get("question_type") == "noul" and actual is not None:
        try:
            actual = float(actual) >= 0.5
        except (TypeError, ValueError):
            pass
    return any(_equivalent(actual, answer) for answer in _gold(case))


def _confidence(row: dict[str, Any], key: str) -> float | None:
    value = row.get(key)
    return (
        float(value)
        if isinstance(value, (float, int)) and not isinstance(value, bool)
        else None
    )


def _latency(rows: list[dict[str, Any]]) -> dict[str, float | None]:
    values = sorted(
        float(row["latency_ms"]) for row in rows if row.get("latency_ms") is not None
    )

    def percentile(p: float) -> float | None:
        if not values:
            return None
        return values[min(len(values) - 1, math.ceil(p * len(values)) - 1)]

    return {
        "count": len(values),
        "p50": percentile(0.50),
        "p90": percentile(0.90),
        "p95": percentile(0.95),
        "p99": percentile(0.99),
    }


def _calibration(rows: list[dict[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for question_type in sorted(
        {str(row.get("question_type", "unknown")) for row in rows}
    ):
        subset = [row for row in rows if row.get("question_type") == question_type]
        if question_type == "noul":
            output[question_type] = {
                "p_yes_buckets": noul_probability_buckets(subset),
                "p_yes_ece": noul_ece(subset),
                "binary_brier": noul_brier(subset),
                "chosen_answer_confidence_buckets": confidence_buckets(
                    subset, "chosen_answer_confidence"
                ),
                "chosen_answer_confidence_ece": expected_calibration_error(
                    subset, "chosen_answer_confidence"
                ),
                "raw_confidence_note": "confidence and answer_confidence are preserved as provider evidence; answer_confidence is P(yes) and is not scored against binary correctness.",
            }
        else:
            output[question_type] = {
                "confidence_buckets": confidence_buckets(subset, "confidence"),
                "answer_confidence_buckets": confidence_buckets(
                    subset, "answer_confidence"
                ),
                "chosen_answer_confidence_buckets": confidence_buckets(
                    subset, "chosen_answer_confidence"
                ),
                "confidence_ece": expected_calibration_error(subset, "confidence"),
                "answer_confidence_ece": expected_calibration_error(
                    subset, "answer_confidence"
                ),
                "chosen_answer_confidence_ece": expected_calibration_error(
                    subset, "chosen_answer_confidence"
                ),
                "brier": brier_score(subset),
            }
    return output


def _summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    count = len(rows)
    correct = sum(bool(row["correct"]) for row in rows)
    margins = sorted(
        float(row["top1_top2_margin"])
        for row in rows
        if row.get("top1_top2_margin") is not None
    )
    score_errors = [
        min(
            abs(float(row["answer"]) - float(value))
            for value in row.get("gold_answers", [])
        )
        for row in rows
        if row.get("question_type") == "score"
        and isinstance(row.get("answer"), (int, float))
        and any(
            isinstance(value, (int, float)) for value in row.get("gold_answers", [])
        )
    ]

    def margin_percentile(percentile: float) -> float | None:
        if not margins:
            return None
        return margins[min(len(margins) - 1, math.ceil(percentile * len(margins)) - 1)]

    return {
        "n": count,
        "accuracy": correct / count if count else None,
        "calibration_by_question_type": _calibration(rows),
        "score_mae": statistics.fmean(score_errors) if score_errors else None,
        "top1_top2_margin": {
            "mean": statistics.fmean(margins) if margins else None,
            "p50": margin_percentile(0.50),
            "p95": margin_percentile(0.95),
            "count": len(margins),
        },
        "latency_ms": _latency(rows),
        "input_tokens": sum(
            int((row.get("usage") or {}).get("input_tokens") or 0) for row in rows
        ),
        "output_tokens": sum(
            int((row.get("usage") or {}).get("output_tokens") or 0) for row in rows
        ),
        "state_tokens": sum(
            int((row.get("usage") or {}).get("state_tokens") or 0) for row in rows
        ),
        "wrong_actions": sum(bool(row.get("wrong_action")) for row in rows),
        "escalations": sum(bool(row.get("escalated")) for row in rows),
        "abstention_accuracy": statistics.fmean(
            bool(row.get("abstained")) == bool(row.get("gold_abstain")) for row in rows
        )
        if rows
        else None,
    }


def evaluate(
    records: list[dict[str, Any]], cases: list[dict[str, Any]]
) -> dict[str, Any]:
    case_by_id = {case["case_id"]: case for case in cases}
    enriched: list[dict[str, Any]] = []
    for original in records:
        row = dict(original)
        case = case_by_id[row["case_id"]]
        row["call_error"] = bool(row.get("error"))
        row["correct"] = is_correct(row, case) if row.get("error") is None else False
        row["gold_answers"] = _gold(case)
        row["expected_answer"] = case.get("expected_answer")
        row["acceptable_answers"] = case.get("acceptable_answers", [])
        row["rationale"] = case.get("rationale")
        row["difficulty"] = case.get("difficulty")
        row["candidate_count"] = len(case.get("candidates", []))
        row["top1_top2_margin"] = top_margin(row)
        expected = case.get("expected_answer")
        if case.get("question_type") == "noul" and isinstance(expected, bool):
            row["gold_key"] = "yes" if expected else "no"
            row["gold_yes"] = expected
        else:
            row["gold_key"] = str(expected)
        answer = str(row.get("answer", ""))
        row["escalated"] = any(
            candidate["semantic_id"] == answer
            and (
                "escalat" in candidate["semantic_id"].casefold()
                or "escalat" in candidate["description"].casefold()
            )
            for candidate in case.get("candidates", [])
        )
        row["wrong_action"] = (
            case.get("question_type") == "choice"
            and not row["correct"]
            and not row["escalated"]
        )
        raw_answer = ((row.get("response") or {}).get("answers") or {}).get(
            "decision"
        ) or {}
        action_info: dict[str, Any] = {}
        action_data = raw_answer.get("action") if isinstance(raw_answer, dict) else None
        if isinstance(action_data, dict):
            action_info = action_data
        row["abstained"] = (
            bool(row.get("escalated")) or action_info.get("act_probability") == 0
        )
        expected = _gold(case)
        row["gold_abstain"] = any(
            str(item).casefold()
            in {"abstain", "escalate", "escalate_to_planner", "escalate_to_reasoner"}
            for item in expected
        )
        enriched.append(row)

    canonical = [row for row in enriched if row.get("permutation_index", 0) == 0]
    permutation_rows = [row for row in enriched if row.get("permutation_index", 0) > 0]
    groupers: dict[str, dict[str, list[dict[str, Any]]]] = {
        "category": defaultdict(list),
        "question_type": defaultdict(list),
        "difficulty": defaultdict(list),
        "candidate_count": defaultdict(list),
        "state_token_bucket": defaultdict(list),
        "error": defaultdict(list),
    }
    for row in canonical:
        state_tokens = (row.get("usage") or {}).get("state_tokens")
        if isinstance(state_tokens, (int, float)):
            row["state_token_bucket"] = (
                "0-63"
                if state_tokens < 64
                else "64-127"
                if state_tokens < 128
                else "128-255"
                if state_tokens < 256
                else "256+"
            )
        else:
            row["state_token_bucket"] = "unreported"
        row["error"] = (
            str((row.get("error") or {}).get("type", "none"))
            if isinstance(row.get("error"), dict)
            else "none"
        )
        for dimension in groupers:
            groupers[dimension][str(row.get(dimension, "unknown"))].append(row)
    grouped_metrics = {
        dimension: {key: _summarize(group) for key, group in groups.items()}
        for dimension, groups in groupers.items()
    }

    thresholds = []
    choice_rows = [row for row in canonical if row.get("question_type") == "choice"]
    for confidence_key in (
        "confidence",
        "answer_confidence",
        "chosen_answer_confidence",
    ):
        for threshold in (0.50, 0.60, 0.70, 0.80, 0.90):
            selected = [
                row
                for row in choice_rows
                if (_confidence(row, confidence_key) or 0) >= threshold
            ]
            for margin_threshold in (0.0, 0.05, 0.10, 0.20):
                gated = [
                    row
                    for row in selected
                    if float(row.get("top1_top2_margin") or 0) >= margin_threshold
                ]
                executable = [
                    row
                    for row in gated
                    if not row.get("escalated")
                    and not row.get("abstained")
                    and not row.get("call_error")
                ]
                thresholds.append(
                    {
                        "confidence": confidence_key,
                        "threshold": threshold,
                        "margin_threshold": margin_threshold,
                        "choice_rows": len(choice_rows),
                        "execution_coverage": len(executable) / len(choice_rows)
                        if choice_rows
                        else None,
                        "execution_accuracy": statistics.fmean(
                            bool(row["correct"]) for row in executable
                        )
                        if executable
                        else None,
                        "wrong_actions_executed": sum(
                            bool(row.get("wrong_action")) for row in executable
                        ),
                        "total_escalations": len(choice_rows) - len(executable),
                        "explicit_escalations": sum(
                            bool(row.get("escalated")) for row in choice_rows
                        ),
                    }
                )

    repeats: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    permutations: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in enriched:
        if row.get("permutation_index", 0) == 0:
            repeats[(row["case_id"], row["variant"])].append(row)
        elif row.get("permutation_index", 0) > 0:
            permutations[(row["case_id"], row["variant"])].append(row)
    agreement = [
        len({str(r.get("answer")) for r in group}) == 1
        for group in repeats.values()
        if len(group) > 1
    ]
    permutation_consistency = [
        len({str(r.get("answer")) for r in group}) == 1
        for group in permutations.values()
        if len(group) > 1
    ]
    selected_positions: dict[str, int] = defaultdict(int)
    for row in permutation_rows:
        order = row.get("candidate_order", [])
        if row.get("answer") in order:
            selected_positions[str(order.index(row["answer"]) + 1)] += 1
        else:
            selected_positions["invalid_or_unmapped"] += 1

    return {
        "overall": _summarize(canonical),
        "permutation_runs": _summarize(permutation_rows),
        "by_category": grouped_metrics["category"],
        "by_question_type": grouped_metrics["question_type"],
        "by_difficulty": grouped_metrics["difficulty"],
        "by_candidate_count": grouped_metrics["candidate_count"],
        "by_state_token_bucket": grouped_metrics["state_token_bucket"],
        "by_error": grouped_metrics["error"],
        "coverage_accuracy_threshold_grid": thresholds,
        "repeat_agreement": statistics.fmean(agreement) if agreement else None,
        "position_permutation_consistency": statistics.fmean(permutation_consistency)
        if permutation_consistency
        else None,
        "position_selection_counts": dict(selected_positions),
        "scored_rows": enriched,
        "note": "Confidence and probabilities are provider outputs; metrics are descriptive and impose no production thresholds.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--scored-output",
        type=Path,
        help="Optional per-request JSONL with evaluator-only gold labels and correctness",
    )
    args = parser.parse_args()
    from .schema import load_cases

    result = evaluate(
        load_records(args.input),
        [case.model_dump(mode="json") for case in load_cases(args.cases)],
    )
    scored_rows = result.pop("scored_rows")
    if args.scored_output is not None:
        args.scored_output.parent.mkdir(parents=True, exist_ok=True)
        with args.scored_output.open("w", encoding="utf-8") as output:
            for row in scored_rows:
                output.write(json.dumps(row, ensure_ascii=False) + "\n")
    result["source_results"] = str(args.input.resolve())
    result["cases"] = str(args.cases.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
