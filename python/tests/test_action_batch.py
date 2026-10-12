"""Queued form actions require fresh same-page verification at every step."""

from __future__ import annotations

import pytest

from browser_agent import BrowserAction, ElementRef
from browser_agent._types import BBox, SemanticElement, SemanticSnapshot, Viewport
from browser_agent.agent.action_batch import (
    PendingActionBatch,
    advance_action_batch,
    mark_batch_action_started,
    prepare_action_batch,
)
from browser_agent.reasoning.contracts import ReasoningAction


def snapshot() -> SemanticSnapshot:
    return SemanticSnapshot(
        url="https://forms.example/account",
        active_tab="tab-main",
        tabs=["tab-main"],
        state_generation=14,
        page_fingerprint="page-account-v1",
        viewport=Viewport(width=1000, height=800),
        elements=[
            element("@name", "textbox", "Name", value=""),
            element("@email", "textbox", "Email", value=""),
            element("@state", "combobox", "State", value=""),
            element("@agree", "checkbox", "Agree", state=[]),
            element("@submit", "button", "Submit"),
        ],
    )


def element(
    ref: str,
    role: str,
    name: str,
    *,
    value: str | None = None,
    state: list[str] | None = None,
) -> SemanticElement:
    return SemanticElement(
        id=len(ref),
        ref=ref,
        generation=14,
        role=role,
        accessible_name=name,
        value=value,
        state=state or [],
        bbox=BBox(x=10, y=10, width=100, height=24),
        fingerprint=f"fingerprint-{ref}",
    )


def make_actions() -> list[ReasoningAction]:
    return [
        ReasoningAction(type="type", target_ref="@name", text="Ada"),
        ReasoningAction(type="type", target_ref="@email", text="ada@example.test"),
        ReasoningAction(type="select", target_ref="@state", value="Karnataka", by="label"),
        ReasoningAction(type="click", target_ref="@submit"),
    ]


def make_authorized(actions: list[ReasoningAction]) -> list[BrowserAction]:
    snap = snapshot()
    return [
        BrowserAction(
            type=action.type,
            target=(
                ElementRef(ref=action.target_ref, generation=snap.state_generation)
                if action.target_ref is not None
                else None
            ),
            text=action.text,
            clear=action.clear,
            submit=action.submit,
            value=action.value,
            by=action.by,
            checked=action.checked,
            key=action.key,
            url=action.url,
        )
        for action in actions
    ]


def prepare(
    actions: list[ReasoningAction] | None = None,
) -> PendingActionBatch | None:
    proposed = actions if actions is not None else make_actions()
    return prepare_action_batch(
        proposed,
        make_authorized(proposed),
        snapshot(),
        run_id="run-1",
        page_id="page-1",
    )


def after_typing(*, other_value: str = "", generation: int = 14) -> SemanticSnapshot:
    current = snapshot()
    current.state_generation = generation
    current.elements[0].value = "Ada"
    current.elements[1].value = other_value
    return current


def test_accepts_bounded_authorized_form_sequence_with_click_last() -> None:
    batch = prepare()

    assert batch is not None
    assert len(batch.actions) == 4
    assert batch.next_action == batch.actions[1]


@pytest.mark.parametrize(
    "actions",
    [
        [ReasoningAction(type="type", target_ref="@name", text=str(index)) for index in range(5)],
        [
            ReasoningAction(type="click", target_ref="@submit"),
            ReasoningAction(type="type", target_ref="@name", text="Ada"),
        ],
        [
            ReasoningAction(type="type", target_ref="@name", text="Ada"),
            ReasoningAction(type="press", key="ENTER"),
        ],
    ],
)
def test_rejects_oversized_nonfinal_click_and_unknown_action_types(
    actions: list[ReasoningAction],
) -> None:
    assert prepare(actions) is None


def test_rejects_actions_that_do_not_match_supplied_candidates() -> None:
    actions = make_actions()
    authorized = make_authorized(actions)
    authorized[0].text = "Grace"

    assert (
        prepare_action_batch(
            actions,
            authorized,
            snapshot(),
            run_id="run-1",
            page_id="page-1",
        )
        is None
    )


def test_accepts_authorized_new_tab_only_batch_with_one_owned_tab_per_step() -> None:
    urls = ["https://one.example/search", "https://two.example/search"]
    actions = [ReasoningAction(type="new_tab", url=url) for url in urls]
    batch = prepare_action_batch(
        actions,
        make_authorized(actions),
        snapshot(),
        run_id="run-1",
        page_id="page-1",
    )
    assert batch is not None
    assert mark_batch_action_started(batch, actions[0])

    first_snapshot = snapshot()
    first_snapshot.tabs.append("tab-one")
    next_action = advance_action_batch(
        batch,
        first_snapshot,
        run_id="run-1",
        page_id="page-1",
        verification_success=True,
        recovery_in_progress=False,
        owned_tab_urls={"tab-one": "https://one.example/search/"},
    )

    assert next_action == actions[1]

    second_snapshot = first_snapshot.model_copy(deep=True)
    second_snapshot.tabs.append("tab-two")
    assert (
        advance_action_batch(
            batch,
            second_snapshot,
            run_id="run-1",
            page_id="page-1",
            verification_success=True,
            recovery_in_progress=False,
            owned_tab_urls={
                "tab-one": "https://one.example/search/",
                "tab-two": "https://two.example/search",
            },
        )
        is None
    )


def test_rejects_wrong_tab_url_and_multiple_tabs_added_at_once() -> None:
    actions = [
        ReasoningAction(type="new_tab", url="https://one.example/search"),
        ReasoningAction(type="new_tab", url="https://two.example/search"),
    ]

    for new_tabs, inventory in (
        (["tab-one"], {"tab-one": "https://wrong.example/search"}),
        (
            ["tab-one", "tab-two"],
            {"tab-one": "https://one.example/search", "tab-two": "https://two.example/search"},
        ),
    ):
        batch = prepare_action_batch(
            actions,
            make_authorized(actions),
            snapshot(),
            run_id="run-1",
            page_id="page-1",
        )
        assert batch is not None
        assert mark_batch_action_started(batch, actions[0])
        current = snapshot()
        current.tabs.extend(new_tabs)

        assert (
            advance_action_batch(
                batch,
                current,
                run_id="run-1",
                page_id="page-1",
                verification_success=True,
                recovery_in_progress=False,
                owned_tab_urls=inventory,
            )
            is None
        )


def test_rejects_tab_batch_after_page_state_interference() -> None:
    actions = [
        ReasoningAction(type="new_tab", url="https://one.example/search"),
        ReasoningAction(type="new_tab", url="https://two.example/search"),
    ]
    batch = prepare_action_batch(
        actions,
        make_authorized(actions),
        snapshot(),
        run_id="run-1",
        page_id="page-1",
    )
    assert batch is not None
    assert mark_batch_action_started(batch, actions[0])
    current = snapshot()
    current.tabs.append("tab-one")
    current.elements[0].value = "user changed this"

    assert (
        advance_action_batch(
            batch,
            current,
            run_id="run-1",
            page_id="page-1",
            verification_success=True,
            recovery_in_progress=False,
            owned_tab_urls={"tab-one": "https://one.example/search"},
        )
        is None
    )


def test_rejects_mixed_form_and_new_tab_batch() -> None:
    actions = [
        ReasoningAction(type="type", target_ref="@name", text="Ada"),
        ReasoningAction(type="new_tab", url="https://one.example/search"),
    ]

    assert (
        prepare_action_batch(
            actions,
            make_authorized(actions),
            snapshot(),
            run_id="run-1",
            page_id="page-1",
        )
        is None
    )


def test_expected_typed_value_allows_next_action_after_verification() -> None:
    batch = prepare()
    assert batch is not None
    assert mark_batch_action_started(batch, batch.actions[0])

    next_action = advance_action_batch(
        batch,
        after_typing(),
        run_id="run-1",
        page_id="page-1",
        verification_success=True,
        recovery_in_progress=False,
    )

    assert next_action == batch.actions[1]


def test_focus_change_after_type_does_not_cancel_batch() -> None:
    batch = prepare()
    assert batch is not None
    assert mark_batch_action_started(batch, batch.actions[0])
    current = after_typing()
    current.focused = "@name"
    name_element = current.by_ref("@name")
    assert name_element is not None
    name_element.state = ["focused"]

    next_action = advance_action_batch(
        batch,
        current,
        run_id="run-1",
        page_id="page-1",
        verification_success=True,
        recovery_in_progress=False,
    )

    assert next_action == batch.actions[1]


def test_expected_select_and_check_mutations_advance_to_final_click() -> None:
    actions = [
        make_actions()[0],
        make_actions()[2],
        ReasoningAction(type="check", target_ref="@agree", checked=True),
        make_actions()[3],
    ]
    batch = prepare_action_batch(
        actions,
        make_authorized(actions),
        snapshot(),
        run_id="run-1",
        page_id="page-1",
    )
    assert batch is not None
    assert mark_batch_action_started(batch, batch.actions[0])
    second = after_typing()
    assert (
        advance_action_batch(
            batch,
            second,
            run_id="run-1",
            page_id="page-1",
            verification_success=True,
            recovery_in_progress=False,
        )
        == batch.actions[1]
    )

    # The second action has been returned and is now the queued prior action.
    second_result = second.model_copy(deep=True)
    state_element = second_result.by_ref("@state")
    assert state_element is not None
    state_element.value = "Karnataka"
    third = advance_action_batch(
        batch,
        second_result,
        run_id="run-1",
        page_id="page-1",
        verification_success=True,
        recovery_in_progress=False,
    )
    assert third == batch.actions[2]

    third_result = second_result.model_copy(deep=True)
    checkbox = third_result.by_ref("@agree")
    assert checkbox is not None
    checkbox.state = ["checked"]
    final = advance_action_batch(
        batch,
        third_result,
        run_id="run-1",
        page_id="page-1",
        verification_success=True,
        recovery_in_progress=False,
    )
    assert final == batch.actions[3]


def test_rejects_unexpected_change_to_another_form_field() -> None:
    batch = prepare()
    assert batch is not None
    assert mark_batch_action_started(batch, batch.actions[0])

    assert (
        advance_action_batch(
            batch,
            after_typing(other_value="user changed this"),
            run_id="run-1",
            page_id="page-1",
            verification_success=True,
            recovery_in_progress=False,
        )
        is None
    )
    assert not batch.actions


@pytest.mark.parametrize(
    ("mutation", "run_id", "page_id", "verified", "recovering"),
    [
        ("generation", "run-1", "page-1", True, False),
        ("ref", "run-1", "page-1", True, False),
        ("fingerprint", "run-1", "page-1", True, False),
        ("page_fingerprint", "run-1", "page-1", True, False),
        ("tabs", "run-1", "page-1", True, False),
        ("geometry", "run-1", "page-1", True, False),
        ("none", "run-2", "page-1", True, False),
        ("none", "run-1", "page-2", True, False),
        ("none", "run-1", "page-1", False, False),
        ("none", "run-1", "page-1", True, True),
    ],
)
def test_clears_batch_on_stale_state_or_failed_gate(
    mutation: str,
    run_id: str,
    page_id: str,
    verified: bool,
    recovering: bool,
) -> None:
    batch = prepare()
    assert batch is not None
    assert mark_batch_action_started(batch, batch.actions[0])
    current = after_typing()
    if mutation == "generation":
        current.state_generation = 15
    elif mutation == "ref":
        current.elements[0].ref = "@replacement"
    elif mutation == "fingerprint":
        current.elements[0].fingerprint = "changed"
    elif mutation == "page_fingerprint":
        current.page_fingerprint = "changed-page"
    elif mutation == "tabs":
        current.tabs = ["tab-other"]
    elif mutation == "geometry":
        rectangle = current.elements[0].bbox
        assert rectangle is not None
        rectangle.x = 50

    assert (
        advance_action_batch(
            batch,
            current,
            run_id=run_id,
            page_id=page_id,
            verification_success=verified,
            recovery_in_progress=recovering,
        )
        is None
    )
    assert batch.actions == ()


def test_batch_can_be_cleared_on_pause_or_replan() -> None:
    batch = prepare()
    assert batch is not None

    batch.clear()

    assert batch.actions == ()
    assert batch.next_action is None
