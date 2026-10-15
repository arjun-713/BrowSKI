"""Model IDs select canonical values; unknown IDs never authorize actions."""

import pytest

from browser_agent.agent.candidate_output import resolve_candidate_output
from browser_agent.decisions import ActionCandidate
from browser_agent.decisions.candidates import CandidateKind
from browser_agent.reasoning import ReasoningAction, ReasoningDecision, ReasoningOutcome


def candidates() -> list[ActionCandidate]:
    return [
        ActionCandidate(
            candidate_id="c01",
            kind=CandidateKind.BROWSER_ACTION,
            description="Type the locally authorized search text",
            action_type="type",
            target_ref="@search",
            text="screen reader labels",
        ),
        ActionCandidate(
            candidate_id="c02",
            kind=CandidateKind.BROWSER_ACTION,
            description="Scroll down",
            action_type="scroll",
            dy=600,
        ),
        ActionCandidate(
            candidate_id="c03",
            kind=CandidateKind.ESCALATE_TO_PLANNER,
            description="Escalate",
        ),
    ]


def test_id_preserves_exact_canonical_text_without_model_reconstruction() -> None:
    result = resolve_candidate_output(
        ReasoningDecision(outcome=ReasoningOutcome.NEXT_ACTION, candidate_id="c01"),
        candidates(),
    )
    assert result.action is not None
    assert result.action.text == "screen reader labels"
    assert result.action.target_ref == "@search"
    assert result.candidate_id is None


def test_id_preserves_exact_scroll_distance() -> None:
    result = resolve_candidate_output(
        ReasoningDecision(outcome=ReasoningOutcome.NEXT_ACTION, candidate_id="c02"),
        candidates(),
    )
    assert result.action is not None
    assert result.action.dy == 600


@pytest.mark.parametrize("candidate_id", ["c00", "c03", "c99"])
def test_unknown_or_escalation_id_cannot_become_executable(candidate_id: str) -> None:
    with pytest.raises(ValueError):
        resolve_candidate_output(
            ReasoningDecision(outcome=ReasoningOutcome.NEXT_ACTION, candidate_id=candidate_id),
            candidates(),
        )


def test_batch_ids_keep_order_and_exact_parameters() -> None:
    result = resolve_candidate_output(
        ReasoningDecision(outcome=ReasoningOutcome.NEXT_ACTION, candidate_ids=["c02", "c01"]),
        candidates(),
    )
    assert [action.type for action in result.candidate_actions] == ["scroll", "type"]
    # Existing batch policy still decides whether this particular sequence is
    # permitted. Resolving IDs does not bypass that policy or queue it.
    assert result.action is None


def test_multiple_output_authorities_are_rejected() -> None:
    with pytest.raises(ValueError):
        ReasoningDecision(
            outcome=ReasoningOutcome.NEXT_ACTION,
            candidate_id="c01",
            candidate_ids=["c02"],
        )


def test_duplicate_candidate_ids_cannot_repeat_a_side_effect() -> None:
    with pytest.raises(ValueError, match="must not repeat"):
        ReasoningDecision(
            outcome=ReasoningOutcome.NEXT_ACTION,
            candidate_ids=["c01", "c01"],
        )


def test_duplicate_legacy_actions_cannot_repeat_a_side_effect() -> None:
    action = ReasoningAction(type="new_tab", url="https://example.invalid/product")
    with pytest.raises(ValueError, match="must not repeat"):
        ReasoningDecision(
            outcome=ReasoningOutcome.NEXT_ACTION,
            candidate_actions=[action, action],
        )


def test_resolver_defends_against_unvalidated_duplicate_id_copy() -> None:
    decision = ReasoningDecision(outcome=ReasoningOutcome.NEXT_ACTION, candidate_id="c01")
    copied = decision.model_copy(update={"candidate_id": None, "candidate_ids": ["c01", "c01"]})
    with pytest.raises(ValueError, match="must be unique"):
        resolve_candidate_output(copied, candidates())
