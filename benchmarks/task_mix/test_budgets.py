"""Budget changes are explicit run policy and do not alter frozen gold."""

from dataclasses import replace

import pytest

from benchmarks.task_mix.budgets import ExecutionPolicy
from benchmarks.task_mix.dataset import load_cases


def test_default_policy_preserves_original_case_limits() -> None:
    case = load_cases("development")[0]
    assert ExecutionPolicy().case_limits(case) == (
        case.max_steps,
        case.max_reasoning_calls,
        min(120, case.max_seconds),
    )


def test_extended_policy_is_bounded_and_leaves_case_unchanged() -> None:
    original = load_cases("development")[0]
    case = replace(original, max_steps=14, max_reasoning_calls=8, max_seconds=100)
    assert ExecutionPolicy(budget_scale=3).case_limits(case) == (42, 24, 180)
    assert case.max_steps == 14
    assert case.max_reasoning_calls == 8
    assert case.gold == original.gold


def test_explicit_timeout_honors_native_holdout_bounds_without_scaling() -> None:
    original = load_cases("development")[0]
    case = replace(original, max_steps=40, max_reasoning_calls=24, max_seconds=180)

    policy = ExecutionPolicy(max_case_seconds=180)

    assert policy.case_limits(case) == (40, 24, 180)
    assert policy.describe()["budget_scale"] == 1
    assert policy.describe()["max_case_seconds"] == 180


def test_default_timeout_still_preserves_original_120_second_cap() -> None:
    case = replace(load_cases("development")[0], max_seconds=180)

    assert ExecutionPolicy().case_limits(case)[2] == 120


@pytest.mark.parametrize(
    "options",
    [
        {"budget_scale": 4},
        {"max_steps": 0},
        {"max_luna_calls": 61},
        {"difficulty": "unknown"},
        {"max_case_seconds": 0},
        {"max_case_seconds": 181},
    ],
)
def test_invalid_or_unbounded_run_policy_is_rejected(
    options: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        ExecutionPolicy(**options)  # type: ignore[arg-type]
