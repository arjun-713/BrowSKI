"""Regressions for private field evidence and false progress/completion."""

from typing import cast

import pytest

from browser_agent._types import (
    BBox,
    SemanticElement,
    SemanticSnapshot,
    TabInfo,
    TaskState,
    Viewport,
)
from browser_agent.agent.task_inventory import TaskInventory
from browser_agent.progress.evidence import (
    evidence_satisfied,
    local_browser_checks,
    semantic_observation,
    task_terminal_satisfied,
)
from browser_agent.progress.task_state import ProgressTracker
from browser_agent.session import BrowserSession


def form(value: str | None = "Smoke Tester") -> SemanticSnapshot:
    return SemanticSnapshot(
        url="https://example.test/form",
        page_fingerprint="form",
        state_generation=1,
        viewport=Viewport(width=800, height=600),
        elements=[
            SemanticElement(
                ref="@full_name",
                role="textbox",
                accessible_name="Full name",
                value=value,
                fingerprint="name",
            ),
            SemanticElement(
                ref="@password",
                role="textbox",
                accessible_name="Password",
                value="private-value",
                fingerprint="password",
            ),
        ],
    )


def test_private_field_values_are_not_in_provider_observation_or_checks() -> None:
    snapshot = form()
    task = TaskState(task='set "Full name" to "Smoke Tester"')
    observation = semantic_observation(snapshot)
    checks = local_browser_checks(task, snapshot, observation)
    assert all(element.value is None for element in observation.elements)
    assert checks == {"field_matches_task:@full_name": True}
    assert "private-value" not in observation.model_dump_json()
    assert "private-value" not in str(checks)


def test_field_match_is_exact_and_only_task_authorized() -> None:
    snapshot = form("Smoke")
    task = TaskState(task='set "Full name" to "Smoke Tester"')
    checks = local_browser_checks(task, snapshot, semantic_observation(snapshot))
    assert checks["field_matches_task:@full_name"] is False
    assert not evidence_satisfied("field_matches_task:@password", task, snapshot, checks)
    assert not evidence_satisfied("Full name field contains Smoke Tester", task, snapshot, checks)


def test_and_conjunction_is_bounded_and_requires_each_closed_check() -> None:
    task = TaskState(task="Fill the authorized fields.")
    snapshot = form()
    evidence = "field_matches_task:@full_name AND field_matches_task:@email"
    checks = {"field_matches_task:@full_name": True, "field_matches_task:@email": False}
    assert not evidence_satisfied(evidence, task, snapshot, checks)
    checks["field_matches_task:@email"] = True
    assert evidence_satisfied(evidence, task, snapshot, checks)
    assert not evidence_satisfied(
        "field_matches_task:@full_name AND invent arbitrary evidence", task, snapshot, checks
    )


def test_literal_visible_text_with_and_is_not_split_into_checks() -> None:
    task = TaskState(task="Read the heading.")
    snapshot = form()
    snapshot.elements.append(
        SemanticElement(
            ref="@heading",
            role="heading",
            text="Research AND Development",
            fingerprint="heading",
            interactable=False,
        )
    )
    assert evidence_satisfied("visible_text:Research AND Development", task, snapshot, {})


def test_offscreen_text_does_not_satisfy_visible_stop_condition() -> None:
    task = TaskState(task='Scroll until "Bottom of the page" is visible.')
    snapshot = form()
    element = SemanticElement(
        ref="@bottom",
        role="generic",
        text="Bottom of the page",
        fingerprint="bottom",
        bbox=BBox(x=0, y=1600, width=200, height=20),
        interactable=False,
    )
    snapshot.elements.append(element)
    snapshot.text_excerpt = "Bottom of the page"
    observation = semantic_observation(snapshot)
    checks = local_browser_checks(task, snapshot, observation)
    assert not task_terminal_satisfied(task, snapshot)
    assert not evidence_satisfied("visible_text:Bottom of the page", task, snapshot, checks)

    element.bbox = BBox(x=0, y=200, width=200, height=20)
    checks = local_browser_checks(task, snapshot, semantic_observation(snapshot))
    assert task_terminal_satisfied(task, snapshot)
    assert evidence_satisfied("visible_text:Bottom of the page", task, snapshot, checks)


def test_checkbox_and_visible_text_compound_evidence_require_both_conditions() -> None:
    snapshot = form()
    snapshot.elements.extend(
        [
            SemanticElement(
                ref="@marketing",
                role="checkbox",
                accessible_name="Marketing emails",
                state=["checked"],
                fingerprint="marketing-checkbox",
            ),
            SemanticElement(
                ref="@saved",
                role="status",
                text="Preferences saved",
                fingerprint="saved-status",
            ),
        ]
    )
    task = TaskState(task='check "Marketing emails"')
    evidence = "checked_matches_task:@marketing;visible_text:Preferences saved"

    checks = local_browser_checks(task, snapshot, semantic_observation(snapshot))
    assert evidence_satisfied(evidence, task, snapshot, checks)

    checkbox = snapshot.by_ref("@marketing")
    assert checkbox is not None
    checkbox.state.clear()
    checks = local_browser_checks(task, snapshot, semantic_observation(snapshot))
    assert not evidence_satisfied(evidence, task, snapshot, checks)


class FakeBrowser:
    def __init__(self, tabs: list[TabInfo]) -> None:
        self._tabs = tabs

    async def tabs(self) -> list[TabInfo]:
        return self._tabs


@pytest.mark.asyncio
async def test_owned_destination_evidence_requires_an_exact_owned_tab() -> None:
    destination = "https://example.test/account"
    task = TaskState(task=f'Open "{destination}" in a new tab')
    page = form()
    page.tabs = ["owned-tab"]
    browser = FakeBrowser([TabInfo(id="owned-tab", target="target", url=destination)])
    inventory = TaskInventory()
    inventory.bind_browser(cast(BrowserSession, browser))

    await inventory.refresh(page, task, {})

    fact = "owned_task_destination:1"
    observation = semantic_observation(page)
    checks = local_browser_checks(task, page, observation)
    assert inventory.destination_checks == {fact: True}
    assert evidence_satisfied(fact, task, page, checks)

    unrelated_page = form()
    unrelated_page.tabs = ["current-tab"]
    unrelated_browser = FakeBrowser(
        [TabInfo(id="other-session-tab", target="other", url=destination)]
    )
    unrelated_inventory = TaskInventory()
    unrelated_inventory.bind_browser(cast(BrowserSession, unrelated_browser))
    unrelated_task = TaskState(task=f'Open "{destination}" in a new tab')

    await unrelated_inventory.refresh(unrelated_page, unrelated_task, {})

    unrelated_checks = local_browser_checks(
        unrelated_task, unrelated_page, semantic_observation(unrelated_page)
    )
    assert unrelated_inventory.destination_checks == {fact: False}
    assert not evidence_satisfied(fact, unrelated_task, unrelated_page, unrelated_checks)


def test_repeated_success_without_state_change_is_not_task_progress() -> None:
    snapshot = form()
    progress = ProgressTracker().compare(snapshot, snapshot, verification_status="SUCCESS")
    assert progress.activity
    assert not progress.progressed
    assert "verification_success" in progress.signals


def test_scrolling_is_progress_even_when_semantic_content_is_unchanged() -> None:
    before = form()
    after = before.model_copy(deep=True, update={"scroll": {"x": 0, "y": 600}})
    progress = ProgressTracker().compare(before, after, verification_status="SUCCESS")
    assert progress.progressed
    assert "viewport_changed" in progress.signals
