"""Task-authorized destinations and owned tabs remain finite model choices."""

from __future__ import annotations

import pytest

from browser_agent._types import SemanticSnapshot
from browser_agent.decisions import ActionCandidate, CandidateKind
from browser_agent.decisions.task_tabs import with_owned_tab_candidates


def choices(task: str, *, tabs: list[str] | None = None) -> list[ActionCandidate]:
    snapshot = SemanticSnapshot(
        url="https://example.test/form",
        active_tab="form",
        tabs=tabs or ["form", "guide"],
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
    return with_owned_tab_candidates(base, task=task, snapshot=snapshot, max_candidates=16)


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
        "Open https://example.test/guide in a new tab",
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
