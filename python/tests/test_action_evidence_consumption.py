"""Runtime action evidence is a single-use witness for milestone progress."""

from __future__ import annotations

import pytest

from browser_agent._types import (
    SemanticElement,
    SemanticSnapshot,
    TaskState,
    Viewport,
    WorkingMemory,
)
from browser_agent.progress.evidence import advance_observed_milestones

_ACTION_WITNESS = "verified_action:click:@pin"


def page(*, favorite_checked: bool = False) -> SemanticSnapshot:
    elements = [
        SemanticElement(
            ref="@item_a",
            role="listitem",
            text="Item A",
            fingerprint="item-a",
            interactable=False,
        ),
        SemanticElement(
            ref="@item_b",
            role="listitem",
            text="Item B",
            fingerprint="item-b",
            interactable=False,
        ),
        SemanticElement(
            ref="@pin",
            role="button",
            accessible_name="Pin selected item",
            fingerprint="pin-button",
        ),
    ]
    if favorite_checked:
        elements.append(
            SemanticElement(
                ref="@favorite",
                role="checkbox",
                accessible_name="Favorite",
                state=["checked"],
                fingerprint="favorite-checkbox",
            )
        )
    return SemanticSnapshot(
        url="https://fixture.test/items",
        title="Items",
        active_tab="main",
        tabs=["main"],
        elements=elements,
        interactive_elements=[item for item in elements if item.interactable],
        state_generation=1,
        page_fingerprint="item-list",
        viewport=Viewport(width=1000, height=800),
    )


def action_task(*, separator: str = ";") -> TaskState:
    return TaskState(
        task="Pin Item A and then Item B.",
        plan_initialized=True,
        milestones=["Pin Item A", "Pin Item B"],
        required_milestones=["Pin Item A", "Pin Item B"],
        current_subgoal="Pin Item A",
        milestone_evidence={
            "Pin Item A": f"visible_text:Item A{separator}{_ACTION_WITNESS}",
            "Pin Item B": f"visible_text:Item B{separator}{_ACTION_WITNESS}",
        },
        deterministic_evidence=[_ACTION_WITNESS],
    )


@pytest.mark.parametrize("separator", [";", " AND "])
def test_one_action_witness_advances_at_most_one_milestone_per_call(
    separator: str,
) -> None:
    task = action_task(separator=separator)
    memory = WorkingMemory(user_goal=task.task)

    completed = advance_observed_milestones(task, memory, page())

    assert completed == ["Pin Item A"]
    assert task.completed == ["Pin Item A"]
    assert _ACTION_WITNESS not in task.deterministic_evidence


def test_consumed_action_witness_cannot_advance_another_milestone_later() -> None:
    task = action_task()
    memory = WorkingMemory(user_goal=task.task)

    first = advance_observed_milestones(task, memory, page())
    second = advance_observed_milestones(task, memory, page())

    assert first == ["Pin Item A"]
    assert second == []
    assert task.completed == ["Pin Item A"]
    assert _ACTION_WITNESS not in task.deterministic_evidence


def test_a_later_verified_click_supplies_a_new_witness_for_the_next_milestone() -> None:
    task = action_task()
    memory = WorkingMemory(user_goal=task.task)

    assert advance_observed_milestones(task, memory, page()) == ["Pin Item A"]

    task.deterministic_evidence.append(_ACTION_WITNESS)
    second = advance_observed_milestones(task, memory, page())

    assert second == ["Pin Item B"]
    assert task.completed == ["Pin Item A", "Pin Item B"]
    assert _ACTION_WITNESS not in task.deterministic_evidence


def test_independent_checkbox_value_can_advance_multiple_milestones() -> None:
    task = TaskState(
        task='Check "Favorite".',
        plan_initialized=True,
        milestones=["Confirm favorite for Item A", "Confirm favorite for Item B"],
        required_milestones=["Confirm favorite for Item A", "Confirm favorite for Item B"],
        milestone_evidence={
            "Confirm favorite for Item A": "visible_text:Item A;checked_matches_task:@favorite",
            "Confirm favorite for Item B": "visible_text:Item B;checked_matches_task:@favorite",
        },
    )
    memory = WorkingMemory(user_goal=task.task)

    completed = advance_observed_milestones(task, memory, page(favorite_checked=True))

    assert completed == ["Confirm favorite for Item A", "Confirm favorite for Item B"]
    assert task.completed == task.required_milestones


def test_click_checkbox_fallback_is_independent_and_does_not_consume_click_event() -> None:
    task = TaskState(
        task='Check "Favorite".',
        plan_initialized=True,
        milestones=["Confirm favorite for Item A", "Confirm favorite for Item B"],
        required_milestones=["Confirm favorite for Item A", "Confirm favorite for Item B"],
        milestone_evidence={
            "Confirm favorite for Item A": "visible_text:Item A;verified_action:click:@favorite",
            "Confirm favorite for Item B": "visible_text:Item B;verified_action:click:@favorite",
        },
        deterministic_evidence=["verified_action:click:@favorite"],
    )
    memory = WorkingMemory(user_goal=task.task)

    completed = advance_observed_milestones(task, memory, page(favorite_checked=True))

    assert completed == task.required_milestones
    assert task.deterministic_evidence == ["verified_action:click:@favorite"]
