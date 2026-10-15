"""M7 contracts for bounded memory, progress, stagnation, recovery, completion."""

from __future__ import annotations

import pytest

from browser_agent._types import (
    BrowserAction,
    ElementRef,
    FailureKind,
    FormSummary,
    SemanticElement,
    SemanticSnapshot,
    SnapshotDelta,
    TaskState,
    WorkingMemory,
)
from browser_agent.agent.graph import action_audit_signature, action_audit_summary
from browser_agent.agent.safety import ActionRiskPolicy, RiskCategory
from browser_agent.progress.task_state import (
    ProgressSignal,
    ProgressTracker,
    StagnationDetector,
    StagnationSample,
    check_completion,
)
from browser_agent.recovery.high_level import RecoveryBudget, RecoveryContext, RecoveryPolicy


def snapshot(
    *,
    url: str = "https://example.test/",
    title: str = "Example",
    fingerprint: str = "a",
    excerpt: str = "",
    active_tab: str = "tab-1",
) -> SemanticSnapshot:
    return SemanticSnapshot(
        url=url,
        title=title,
        page_fingerprint=fingerprint,
        state_generation=1,
        text_excerpt=excerpt,
        active_tab=active_tab,
    )


def test_working_memory_keeps_structured_fields_and_bounds_events_and_facts() -> None:
    memory = WorkingMemory(
        user_goal="Update account",
        constraints=["Do not submit payment"],
        current_subgoal="Change address",
        max_events=3,
    )
    for index in range(8):
        memory.record_event(f"  verified   step {index}  ")
    memory.remember_fact("address", "42 Example Road")
    assert memory.user_goal == "Update account"
    assert memory.facts["address"] == "42 Example Road"
    assert len(memory.recent_steps) == 3
    assert memory.recent_steps[-1] == "verified step 7"
    restored = WorkingMemory.model_validate(memory.model_dump(mode="json"))
    assert restored.acquired_facts == memory.acquired_facts
    assert restored.constraints == memory.constraints


def test_progress_tracker_distinguishes_activity_from_task_progress() -> None:
    before = snapshot()
    same = snapshot()
    activity_only = ProgressTracker().compare(
        before, same, delta=SnapshotDelta(moved=["@save"]), verification_status="UNCERTAIN"
    )
    assert activity_only.activity
    assert not activity_only.progressed

    next_page = snapshot(url="https://example.test/saved", fingerprint="b", excerpt="Saved")
    progress = ProgressTracker().compare(before, next_page, verification_status="SUCCESS")
    assert progress.progressed
    assert ProgressSignal.DOCUMENT_TRANSITION in progress.signals
    assert ProgressSignal.VERIFICATION_SUCCESS in progress.signals

    text_only_change = ProgressTracker().compare(
        snapshot(excerpt="clicked 1 times"),
        snapshot(excerpt="clicked 2 times"),
    )
    assert text_only_change.progressed
    assert ProgressSignal.SNAPSHOT_CHANGE in text_only_change.signals


def test_stagnation_detects_repeats_cycles_uncertainty_and_resets_on_progress() -> None:
    repeated = StagnationDetector(window=4)
    for _ in range(3):
        repeated.observe(
            StagnationSample(
                state_fingerprint="same",
                action_signature="click:@save",
                verification_status="NO_EFFECT",
            )
        )
    assert repeated.is_stagnant

    cycle = StagnationDetector()
    for fingerprint in ("a", "b", "a", "b"):
        cycle.observe(
            StagnationSample(
                state_fingerprint=fingerprint,
                action_signature="scroll",
                verification_status="UNCERTAIN",
            )
        )
    assert cycle.is_stagnant
    cycle.observe(
        StagnationSample(
            state_fingerprint="c",
            action_signature="click:@next",
            verification_status="SUCCESS",
            progressed=True,
        )
    )
    assert not cycle.is_stagnant


def test_recovery_ladder_is_explicit_and_budgeted() -> None:
    policy = RecoveryPolicy()
    budget = RecoveryBudget(max_mechanical_repairs=0)
    context = RecoveryContext(
        failure_kind=FailureKind.VERIFICATION,
        alternate_action_available=True,
        system_one_available=True,
        reasoning_available=True,
        very_complex=True,
    )
    steps = [policy.next_step(context, budget).step.value for _ in range(7)]
    assert steps == [
        "reobserve",
        "alternate_bounded_action",
        "system_one_classification",
        "luna_normal_replan",
        "complexity_gate",
        "luna_high_replan",
        "ask_user",
    ]
    terminal = policy.next_step(context, budget)
    assert terminal.step.value == "terminate"
    assert "budget exhausted" in terminal.reason


def test_recovery_ladder_stops_after_one_normal_replan_when_gate_is_normal() -> None:
    policy = RecoveryPolicy()
    budget = RecoveryBudget(max_mechanical_repairs=0)
    context = RecoveryContext(
        failure_kind=FailureKind.VERIFICATION,
        alternate_action_available=True,
        system_one_available=True,
        reasoning_available=True,
    )

    steps = [policy.next_step(context, budget).step.value for _ in range(5)]

    assert steps == [
        "reobserve",
        "alternate_bounded_action",
        "system_one_classification",
        "luna_normal_replan",
        "complexity_gate",
    ]
    assert policy.next_step(context, budget).step.value == "ask_user"
    assert budget.normal_replans == 1
    assert budget.high_replans == 0


def test_completion_requires_verified_action_milestones_and_visible_evidence() -> None:
    task = TaskState(
        task="Save the profile",
        milestones=["profile_saved"],
        milestone_evidence={"profile_saved": "Profile saved"},
        required_evidence=["Profile saved"],
        completed=["profile_saved"],
    )
    visible = snapshot(excerpt="Profile saved")
    missing_evidence = snapshot(excerpt="Still editing")

    assert not check_completion(task, visible, verified_action=False)
    assert not check_completion(task, missing_evidence, verified_action=True)
    assert check_completion(task, visible, verified_action=True)
    task.completed.clear()
    assert not check_completion(task, visible, verified_action=True)


def test_risk_policy_flags_submission_and_keeps_navigation_low_risk() -> None:
    page = snapshot()
    page.forms = [FormSummary(submit="@submit")]
    policy = ActionRiskPolicy()

    submit = policy.assess(
        BrowserAction(
            type="click",
            target=ElementRef(ref="@submit", id=2, generation=1),
        ),
        page,
    )
    navigation = policy.assess(BrowserAction(type="navigate", url="https://example.test"), page)
    enter = policy.assess(BrowserAction(type="press", key="Enter"), page)

    assert submit.category == RiskCategory.HIGH
    assert navigation.category == RiskCategory.LOW
    assert enter.category == RiskCategory.HIGH


@pytest.mark.parametrize(
    "label",
    [
        "Place order",
        "Authorize payment",
        "Donate",
        "Confirm purchase",
        "Cancel subscription",
        "Update account security",
        "Modify security settings",
        "Reserve this seat",
        "Reserve a workshop seat",
        "Book this flight",
        "Book a hotel room",
    ],
)
def test_risk_policy_flags_common_consequential_labels(label: str) -> None:
    page = snapshot()
    page.elements.append(
        SemanticElement(
            ref="@control",
            fingerprint="test-control",
            role="button",
            accessible_name=label,
            interactable=True,
        )
    )

    risk = ActionRiskPolicy().assess(
        BrowserAction(type="click", target=ElementRef(ref="@control", id=2, generation=1)),
        page,
    )

    assert risk.category == RiskCategory.HIGH


@pytest.mark.parametrize("label", ["Review order history", "Confirm email"])
def test_risk_policy_does_not_flag_unrelated_labels_as_high_risk(label: str) -> None:
    page = snapshot()
    page.elements.append(
        SemanticElement(
            ref="@control",
            fingerprint="test-control",
            role="button",
            accessible_name=label,
            interactable=True,
        )
    )

    risk = ActionRiskPolicy().assess(
        BrowserAction(type="click", target=ElementRef(ref="@control", id=2, generation=1)),
        page,
    )

    assert risk.category == RiskCategory.MEDIUM


def test_action_history_summary_does_not_retain_sensitive_action_values() -> None:
    action = {
        "type": "type",
        "target": {"ref": "@password", "id": 2},
        "text": "private-password",
        "url": "https://example.test/?token=secret",
    }

    assert action_audit_summary(action) == {"type": "type", "target_ref": "@password"}
    assert action_audit_signature(action) == "type:@password"
