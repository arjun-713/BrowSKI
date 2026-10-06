from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "python" / "src"))
sys.path.insert(0, str(ROOT))

from browser_agent.decisions.laya import LayaProvider

from benchmarks.laya.calibration import (
    brier_score,
    confidence_buckets,
    expected_calibration_error,
)
from benchmarks.laya.evaluate import evaluate
from benchmarks.laya.interface import RecordingJsonTransport, evaluate_case
from benchmarks.laya.schema import BenchmarkCase, load_cases


def choice_case(**updates):
    data = {
        "case_id": "case-1",
        "category": "prerequisite",
        "difficulty": "easy",
        "task": "Find a role in Oslo",
        "current_subgoal": "Set the location before searching",
        "browser_state": {
            "page": "Jobs",
            "url": "https://example.invalid/jobs",
            "state_generation": 4,
            "elements": [
                {
                    "ref": "@location",
                    "role": "textbox",
                    "value": "",
                    "state": [],
                    "interactable": True,
                },
                {
                    "ref": "@search",
                    "role": "button",
                    "name": "Search",
                    "state": [],
                    "interactable": True,
                },
            ],
            "noise_elements": [],
        },
        "recent_action": None,
        "recent_outcome": None,
        "relevant_delta": None,
        "constraints": ["Do not search until the location is set"],
        "question_type": "choice",
        "question": "Choose the best next action.",
        "candidates": [
            {"semantic_id": "set-location", "description": "Type Oslo in @location."},
            {
                "semantic_id": "search-now",
                "description": "Click Search before setting location.",
            },
            {"semantic_id": "escalate", "description": "Escalate to the planner."},
        ],
        "criteria": None,
        "expected_answer": "set-location",
        "acceptable_answers": [],
        "rationale": "The location is a prerequisite.",
        "position_probe": True,
    }
    data.update(updates)
    return BenchmarkCase.model_validate(data)


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["baseline", "tuned"])
async def test_gold_and_rationale_never_reach_model_payload(variant):
    case = choice_case()
    captured = {}
    raw = '{"model":"fake","answers":{"decision":{"type":"choice","choice":"c01","probabilities":{"c01":0.8,"c02":0.1,"c03":0.1},"confidence":0.4,"answer_confidence":0.8}},"usage":{"input_tokens":12,"output_tokens":0,"state_tokens":8},"routing":{"model":"fake-route"}}'

    def fake_transport(method, url, payload, timeout, headers):
        captured.update(payload=payload, method=method, url=url)
        return json.loads(raw), raw

    recorder = RecordingJsonTransport(fake_transport)
    provider = LayaProvider(transport=recorder, endpoint_url="http://fake.invalid")
    row = await evaluate_case(provider, recorder, case, variant=variant)
    serialized = json.dumps(captured["payload"])
    assert "expected_answer" not in serialized
    assert "acceptable_answers" not in serialized
    assert "rationale" not in serialized
    assert '"category"' not in serialized
    assert row["response_raw"] == raw
    assert row["raw_probabilities"]["set-location"] == 0.8
    assert row["top1_probability"] == 0.8
    assert row["top2_probability"] == 0.1
    assert row["probability_margin"] == pytest.approx(0.7)
    assert row["confidence"] == 0.4
    assert row["answer_confidence"] == 0.8
    assert row["model"] == "fake"
    assert row["routing"]["model"] == "fake-route"
    assert row["usage"]["state_tokens"] == 8
    assert row["answer"] == "set-location"
    assert row["raw_probabilities"]["set-location"] == 0.8
    assert captured["payload"]["questions"]["decision"]["criteria"] == {
        "c01": "Type Oslo in @location.",
        "c02": "Click Search before setting location.",
        "c03": "Escalate to the planner.",
    }


@pytest.mark.asyncio
async def test_baseline_mirrors_production_shape_including_noise_elements():
    case = choice_case(
        browser_state={
            "page": "Jobs",
            "url": "https://example.invalid/jobs",
            "state_generation": 4,
            "elements": [{"ref": "@location", "role": "textbox", "interactable": True}],
            "noise_elements": [
                {
                    "ref": "@noise",
                    "role": "link",
                    "name": "Noise",
                    "interactable": False,
                }
            ],
        }
    )
    captured = {}
    raw = '{"model":"fake","answers":{"decision":{"type":"choice","choice":"c01","probabilities":{"c01":0.8,"c02":0.1,"c03":0.1},"confidence":0.4,"answer_confidence":0.8}}}'

    def fake_transport(method, url, payload, timeout, headers):
        captured.update(payload=payload)
        return json.loads(raw), raw

    recorder = RecordingJsonTransport(fake_transport)
    provider = LayaProvider(transport=recorder, endpoint_url="http://fake.invalid")
    await evaluate_case(provider, recorder, case, variant="baseline")
    elements = captured["payload"]["state"]["observation"]["elements"]
    assert [element["ref"] for element in elements] == ["@location", "@noise"]


@pytest.mark.asyncio
async def test_score_question_and_exact_proposal_reach_laya_without_gold_or_rationale():
    data = choice_case().model_dump(mode="json")
    data.update(
        {
            "question_type": "score",
            "question": "Rate the plan. Proposed action: review the phone value, then save only that field.",
            "candidates": [],
            "criteria": {
                "0": "Wrong action.",
                "1": "Incomplete.",
                "2": "Mostly correct.",
                "3": "Correct and verified.",
            },
            "expected_answer": 3,
            "rationale": "The proposal respects the constraint.",
            "position_probe": False,
        }
    )
    case = BenchmarkCase.model_validate(data)
    captured = {}
    raw = '{"model":"fake","answers":{"decision":{"type":"score","score":3,"probabilities":{"0":0.0,"1":0.0,"2":0.0,"3":1.0},"confidence":1.0,"answer_confidence":1.0}}}'

    def fake_transport(method, url, payload, timeout, headers):
        captured.update(payload=payload)
        return json.loads(raw), raw

    recorder = RecordingJsonTransport(fake_transport)
    provider = LayaProvider(transport=recorder, endpoint_url="http://fake.invalid")
    row = await evaluate_case(provider, recorder, case, variant="baseline")
    payload = json.dumps(captured["payload"])
    assert (
        "Proposed action: review the phone value, then save only that field." in payload
    )
    assert "expected_answer" not in payload and "acceptable_answers" not in payload
    assert "rationale" not in payload and '"category"' not in payload
    assert row["answer"] == 3.0


def test_schema_rejects_duplicate_candidate_ids_and_nonchoice_permutation():
    data = choice_case().model_dump(mode="json")
    data["candidates"][1]["semantic_id"] = data["candidates"][0]["semantic_id"]
    with pytest.raises(ValueError):
        BenchmarkCase.model_validate(data)


def test_reviewed_v1_fixture_validates_all_cases():
    fixture = ROOT / "benchmarks" / "laya" / "benchmark_v1.jsonl"
    cases = load_cases(fixture)
    assert len(cases) == 80
    data = choice_case().model_dump(mode="json")
    data["question_type"] = "noul"
    data["candidates"] = []
    with pytest.raises(ValueError):
        BenchmarkCase.model_validate(data)


def test_calibration_utilities_are_descriptive_and_handle_empty_data():
    rows = [
        {
            "confidence": 0.9,
            "correct": True,
            "raw_probabilities": {"yes": 0.9, "no": 0.1},
            "gold_key": "yes",
        },
        {
            "confidence": 0.8,
            "correct": False,
            "raw_probabilities": {"yes": 0.8, "no": 0.2},
            "gold_key": "no",
        },
    ]
    assert len(confidence_buckets(rows, "confidence")) == 10
    assert expected_calibration_error(rows, "confidence") == pytest.approx(0.45)
    assert brier_score(rows) == pytest.approx(0.65)
    assert expected_calibration_error([], "confidence") is None


def test_threshold_grid_does_not_count_escalations_as_executed_actions():
    case = {
        "case_id": "execution-case",
        "question_type": "choice",
        "difficulty": "easy",
        "category": "next_action",
        "expected_answer": "go",
        "acceptable_answers": [],
        "candidates": [
            {"semantic_id": "go", "description": "Click the target."},
            {
                "semantic_id": "ESCALATE_TO_REASONER",
                "description": "Escalate to the planner.",
            },
        ],
    }
    records = [
        {
            "case_id": "execution-case",
            "variant": "baseline",
            "repeat": 1,
            "permutation_index": 0,
            "question_type": "choice",
            "answer": "ESCALATE_TO_REASONER",
            "confidence": 0.99,
            "answer_confidence": 0.99,
            "chosen_answer_confidence": 0.99,
            "raw_probabilities": {"go": 0.01, "ESCALATE_TO_REASONER": 0.99},
            "response": {"answers": {"decision": {"action": {"act_probability": 1}}}},
            "usage": {},
            "latency_ms": 1,
        },
        {
            "case_id": "execution-case",
            "variant": "baseline",
            "repeat": 2,
            "permutation_index": 0,
            "question_type": "choice",
            "answer": "go",
            "confidence": 0.8,
            "answer_confidence": 0.8,
            "chosen_answer_confidence": 0.8,
            "raw_probabilities": {"go": 0.8, "ESCALATE_TO_REASONER": 0.2},
            "response": {"answers": {"decision": {"action": {"act_probability": 1}}}},
            "usage": {},
            "latency_ms": 1,
        },
    ]
    report = evaluate(records, [case])
    row = next(
        item
        for item in report["coverage_accuracy_threshold_grid"]
        if item["confidence"] == "confidence"
        and item["threshold"] == 0.5
        and item["margin_threshold"] == 0
    )
    assert row["execution_coverage"] == pytest.approx(0.5)
    assert row["execution_accuracy"] == 1
    assert row["wrong_actions_executed"] == 0
    assert row["total_escalations"] == 1


def test_noul_calibration_uses_raw_p_yes_against_gold_yes_rate():
    case = {
        "case_id": "noul-case",
        "question_type": "noul",
        "difficulty": "easy",
        "category": "task_completion",
        "expected_answer": False,
        "acceptable_answers": [],
        "candidates": [],
    }
    row = {
        "case_id": "noul-case",
        "variant": "baseline",
        "repeat": 1,
        "question_type": "noul",
        "answer": 0.2,
        "noul_p_yes": 0.2,
        "raw_probabilities": {"yes": 0.2, "no": 0.8},
        "confidence": 0.2,
        "answer_confidence": 0.2,
        "chosen_answer_confidence": 0.8,
        "response": {"answers": {"decision": {"action": {"act_probability": 1}}}},
        "usage": {},
        "latency_ms": 1,
    }
    report = evaluate([row], [case])
    calibration = report["by_question_type"]["noul"]["calibration_by_question_type"][
        "noul"
    ]
    assert calibration["p_yes_ece"] == pytest.approx(0.2)
    assert calibration["binary_brier"] == pytest.approx(0.04)
    assert calibration["chosen_answer_confidence_ece"] == pytest.approx(0.2)


def test_position_permutations_do_not_change_canonical_accuracy_denominator():
    case = {
        "case_id": "position-case",
        "question_type": "choice",
        "difficulty": "easy",
        "category": "next_action",
        "expected_answer": "first-action",
        "acceptable_answers": [],
        "candidates": [
            {"semantic_id": "first-action", "description": "Do the first action."},
            {"semantic_id": "second-action", "description": "Do the second action."},
        ],
    }
    common = {
        "case_id": "position-case",
        "variant": "baseline",
        "question_type": "choice",
        "confidence": 0.8,
        "answer_confidence": 0.8,
        "chosen_answer_confidence": 0.8,
        "usage": {},
        "latency_ms": 1,
        "raw_probabilities": {"first-action": 0.8, "second-action": 0.2},
    }
    records = [
        {
            **common,
            "repeat": 1,
            "permutation_index": 0,
            "answer": "first-action",
            "candidate_order": ["first-action", "second-action"],
        },
        {
            **common,
            "repeat": 0,
            "permutation_index": 1,
            "answer": "first-action",
            "candidate_order": ["second-action", "first-action"],
        },
    ]
    report = evaluate(records, [case])
    assert report["overall"]["n"] == 1
    assert report["permutation_runs"]["n"] == 1
    assert report["position_selection_counts"] == {"2": 1}
