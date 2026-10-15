"""Bind model-selected IDs to canonical actions without model-generated values."""

from browser_agent.decisions.candidates import ActionCandidate
from browser_agent.reasoning.contracts import ReasoningAction, ReasoningDecision


def resolve_candidate_output(
    decision: ReasoningDecision, candidates: list[ActionCandidate]
) -> ReasoningDecision:
    if decision.candidate_id is None and not decision.candidate_ids:
        return decision
    by_id = {f"c{index:02d}": item for index, item in enumerate(candidates, start=1)}
    ids = [decision.candidate_id] if decision.candidate_id is not None else decision.candidate_ids
    if len(set(ids)) != len(ids):
        raise ValueError("Selected candidate IDs must be unique.")
    actions: list[ReasoningAction] = []
    for candidate_id in ids:
        candidate = by_id.get(candidate_id)
        if candidate is None or candidate.action_type is None:
            raise ValueError("Selected candidate is not an authorized browser action.")
        actions.append(
            ReasoningAction(
                type=candidate.action_type,
                target_ref=candidate.target_ref,
                text=candidate.text,
                value=candidate.value,
                by=candidate.selection_by,
                checked=candidate.checked,
                url=candidate.url,
                tab=candidate.tab,
                dx=candidate.dx,
                dy=candidate.dy,
            )
        )
    return decision.model_copy(
        update={
            "candidate_id": None,
            "candidate_ids": [],
            "action": actions[0] if decision.candidate_id is not None else None,
            "candidate_actions": actions if decision.candidate_id is None else [],
        }
    )
