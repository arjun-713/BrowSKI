"""Focused regressions for progress and completion evidence boundaries."""

from browser_agent._types import (
    BBox,
    SemanticElement,
    SemanticSnapshot,
    TaskState,
    Viewport,
    WorkingMemory,
)
from browser_agent.progress.evidence import advance_observed_milestones
from browser_agent.progress.task_state import ProgressTracker, check_completion


def snapshot(*elements: SemanticElement, tabs: list[str] | None = None) -> SemanticSnapshot:
    return SemanticSnapshot(
        url="https://example.test/settings",
        page_fingerprint="settings",
        state_generation=1,
        viewport=Viewport(width=800, height=600),
        tabs=tabs or ["tab-1"],
        active_tab="tab-1",
        elements=list(elements),
    )


def test_opening_an_additional_tab_alone_is_activity_not_progress() -> None:
    before = snapshot()
    after = before.model_copy(deep=True, update={"tabs": ["tab-1", "tab-2"]})

    report = ProgressTracker().compare(before, after)

    assert report.activity
    assert not report.progressed
    assert "tab_changed" in report.signals


def test_offscreen_required_evidence_cannot_complete_a_task() -> None:
    task = TaskState(task="Save the profile", required_evidence=["Background saved"])
    page = snapshot(
        SemanticElement(
            ref="@confirmation",
            role="generic",
            text="Background saved",
            fingerprint="confirmation",
            bbox=BBox(x=0, y=1400, width=200, height=20),
            interactable=False,
        )
    )

    assert not check_completion(task, page, verified_action=True)


def test_later_milestone_cannot_complete_while_an_earlier_condition_is_unmet() -> None:
    task = TaskState(
        task="Update settings",
        required_milestones=["Open preferences", "Enable reminders", "Save settings"],
        milestone_evidence={
            "Open preferences": "visible_text:Preferences",
            "Enable reminders": "visible_text:Reminders enabled",
            "Save settings": "visible_text:Settings saved",
        },
    )
    page = snapshot(
        SemanticElement(
            ref="@heading",
            role="generic",
            text="Preferences",
            fingerprint="heading",
        ),
        SemanticElement(
            ref="@reminders",
            role="checkbox",
            accessible_name="Reminders",
            state=[],
            fingerprint="reminders-checkbox",
        ),
    )
    page.elements.append(
        SemanticElement(
            ref="@status",
            role="status",
            text="Settings saved",
            fingerprint="save-status",
        )
    )

    completed = advance_observed_milestones(task, WorkingMemory(), page)

    assert completed == ["Open preferences"]
    assert task.completed == ["Open preferences"]
    assert "Save settings" not in task.completed
