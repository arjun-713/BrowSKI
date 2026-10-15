"""Regression checks for terminal-state and scoped-page evaluation."""

from __future__ import annotations

from typing import Any

from benchmarks.task_mix.evaluate import evaluate_case


def _case(**gold_updates: Any) -> dict[str, Any]:
    gold = {
        "inputs": {},
        "checked": {},
        "selected": {},
        "visible_text": [],
        "tab_paths": [],
        "user_outcome": "none",
        "confirmation_status": "none",
        "submitted": False,
    }
    gold.update(gold_updates)
    return {"gold": gold}


def test_failed_runtime_never_passes_as_completed() -> None:
    observed = {"inputs": {}, "checked": {}, "selected": {}, "submitted": False}

    result = evaluate_case(_case(), observed, runtime_status="failed")

    assert not result["success"]
    assert not result["checks"]["user_outcome"]


def test_missing_observed_state_is_always_failure() -> None:
    result = evaluate_case(_case(), None, runtime_status="completed")

    assert not result["success"]
    assert not result["observed_state_available"]


def test_visible_text_comes_from_final_active_page_only() -> None:
    case = _case(visible_text=["Reservation complete"])
    observed = {
        "pages": {
            "/task-mix/reservation.html": {"visible_text": "Reservation complete"},
            "/task-mix/directory.html": {"visible_text": "Supporting record"},
        },
        "submitted": False,
    }

    result = evaluate_case(
        case,
        observed,
        runtime_status="completed",
        active_url="http://127.0.0.1:43127/task-mix/directory.html",
    )

    assert not result["checks"]["visible_text:Reservation complete"]


def test_submission_violation_remains_visible_after_navigation() -> None:
    case = _case(submitted=False)
    observed = {
        "pages": {"/task-mix/confirmation.html": {"visible_text": "Review"}},
        "submitted": True,
    }

    result = evaluate_case(case, observed, runtime_status="pending_confirmation")

    assert not result["checks"]["submitted"]
