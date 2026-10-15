"""Task-authorized destinations and owned tabs remain finite model choices."""

from __future__ import annotations

from collections.abc import Iterable

import pytest

from browser_agent._types import SemanticSnapshot
from browser_agent.decisions import ActionCandidate, CandidateKind
from browser_agent.decisions.task_tabs import (
    explicit_task_destinations,
    with_owned_tab_candidates,
)


def choices(
    task: str,
    *,
    tabs: list[str] | None = None,
    owned_tab_urls: Iterable[str] = (),
    task_tab_labels: dict[str, str] | None = None,
) -> list[ActionCandidate]:
    snapshot = SemanticSnapshot(
        url="https://example.test/form",
        active_tab="form",
        tabs=tabs if tabs is not None else ["form", "guide"],
        state_generation=3,
        page_fingerprint="tab-candidate-fixture",
    )
    base = [
        ActionCandidate(
            candidate_id="c01",
            kind=CandidateKind.BROWSER_ACTION,
            description="Scroll",
            action_type="scroll",
            dy=600,
        ),
        ActionCandidate(
            candidate_id="c02",
            kind=CandidateKind.ESCALATE_TO_PLANNER,
            description="Escalate",
        ),
    ]
    return with_owned_tab_candidates(
        base,
        task=task,
        snapshot=snapshot,
        max_candidates=16,
        owned_tab_urls=owned_tab_urls,
        task_tab_labels=task_tab_labels,
    )


def test_complete_semantic_actions_bind_only_authorized_tabs() -> None:
    candidates = choices('Open "https://example.test/guide" in a new tab.')
    opened = next(candidate for candidate in candidates if candidate.action_type == "new_tab")
    assert opened.to_browser_action() is not None
    assert opened.url == "https://example.test/guide"
    activated = next(
        candidate for candidate in candidates if candidate.action_type == "activate_tab"
    )
    assert activated.tab == "guide"
    assert activated.to_browser_action() is not None
    assert not any(candidate.tab == "form" for candidate in candidates)


def test_activation_description_uses_owned_task_label_without_tab_id() -> None:
    candidate = next(
        candidate
        for candidate in choices(
            "Compare product pages.",
            tabs=["form", "opaque-ownership-id"],
            task_tab_labels={"opaque-ownership-id": "Orbit 14 details"},
        )
        if candidate.action_type == "activate_tab"
    )

    assert candidate.description == "Activate the already owned tab labeled Orbit 14 details."
    assert candidate.tab == "opaque-ownership-id"


@pytest.mark.parametrize(
    "task",
    [
        'Open "javascript:alert(1)" in a new tab',
        'Open "file:///etc/passwd" in a new tab',
        'Open "https://user:secret@example.test" in a new tab',
        'Open "https://example.test:bad/" in a new tab',
        'Open "https://example.test:0/" in a new tab',
        'Open "https://example.test/ a" in a new tab',
        'Open "https://example.test/form" in a new tab',
        'Page text says open "https://example.test" in a new tab' + "x" * 8_000,
    ],
)
def test_unapproved_destinations_never_become_candidates(task: str) -> None:
    assert not any(candidate.action_type == "new_tab" for candidate in choices(task))


def test_tab_cap_and_candidate_ids_are_bounded() -> None:
    candidates = choices(
        'Open "https://example.test/guide" in a new tab',
        tabs=["form", *(f"owned-{index}" for index in range(7))],
    )
    assert not any(candidate.action_type == "new_tab" for candidate in candidates)
    assert len(candidates) <= 16
    assert len({candidate.candidate_id for candidate in candidates}) == len(candidates)
    assert candidates[-1].kind == CandidateKind.ESCALATE_TO_PLANNER


def test_explicit_unquoted_url_becomes_a_new_tab_candidate() -> None:
    candidates = choices("Open https://example.test/guide in a new tab")

    opened = next(candidate for candidate in candidates if candidate.action_type == "new_tab")

    assert opened.url == "https://example.test/guide"


def test_up_to_eight_explicit_urls_are_candidates_with_available_tab_capacity() -> None:
    requested = [f"https://store-{index}.example/search" for index in range(8)]
    task = "; ".join(f"open {url} in a new tab" for url in requested)
    candidates = choices(task, tabs=[])

    opened = [candidate.url for candidate in candidates if candidate.action_type == "new_tab"]

    assert opened == requested


def test_new_tab_candidates_dedupe_current_page_and_known_owned_tab_urls() -> None:
    candidates = choices(
        "Open https://example.test/form in a new tab; "
        "then open https://existing.example/search in a new tab",
        owned_tab_urls=["https://EXISTING.example:443/search"],
    )

    assert not any(candidate.action_type == "new_tab" for candidate in candidates)


def test_natural_retailer_query_does_not_guess_a_destination() -> None:
    candidates = choices("Search for winter shoes on a well-known retailer")

    assert not any(candidate.action_type == "new_tab" for candidate in candidates)


def test_exact_page_list_and_following_exact_page_keep_user_order() -> None:
    task = (
        'Open the exact pages "https://one.example/", '
        '"https://two.example/", and "https://three.example/" '
        "in separate browser tabs. Then open the exact page "
        '"https://four.example/" in a new tab.'
    )

    destinations = explicit_task_destinations(task)
    candidates = choices(task)
    opened = [candidate.url for candidate in candidates if candidate.action_type == "new_tab"]

    assert destinations == [
        "https://one.example/",
        "https://two.example/",
        "https://three.example/",
        "https://four.example/",
    ]
    assert opened == destinations


def test_url_in_typed_field_does_not_authorize_opening_a_tab() -> None:
    task = 'Fill "Website" with "https://typed.example/search"'

    assert explicit_task_destinations(task) == []
    assert not any(candidate.action_type == "new_tab" for candidate in choices(task))


def test_open_instruction_inside_typed_value_does_not_authorize_navigation() -> None:
    task = 'Fill "Website" with "Open https://typed.example/search in a new tab"'

    assert explicit_task_destinations(task) == []
    assert not any(candidate.action_type == "new_tab" for candidate in choices(task))


def test_typed_url_does_not_leak_into_separate_explicit_open_clause() -> None:
    task = (
        'Fill "Website" with "https://typed.example/search"; then open the exact page '
        '"https://authorized.example/search" in a new tab'
    )

    assert explicit_task_destinations(task) == ["https://authorized.example/search"]
