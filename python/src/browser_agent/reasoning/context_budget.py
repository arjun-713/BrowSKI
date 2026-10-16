"""Fit semantic page context without dropping task policy or actionable targets."""

from __future__ import annotations

import re

from browser_agent.decisions.candidate_ranking import rank_observation_for_candidates
from browser_agent.reasoning.contracts import ReasoningContext


class ContextBudgetExceeded(ValueError):
    """Required task and target context cannot fit the outbound budget."""


def fit_observation_context(
    context: ReasoningContext,
    *,
    max_characters: int,
) -> ReasoningContext:
    """Drop lower-priority page elements, preserving every retained field verbatim.

    The full browser observation remains local for execution and verification.
    Task constraints, memory, candidates and proof checks are never shortened.
    Candidate targets, referenced evidence, focus and their parents are required.
    """
    if len(context.model_dump_json(exclude_none=True)) <= max_characters:
        return context

    observation = context.observation
    references = " ".join(
        [
            *context.candidate_options.values(),
            *context.browser_checks,
            *context.task.milestone_evidence.values(),
            *context.task.required_link_refs,
        ]
    )
    required = {
        element.ref
        for element in observation.elements
        if re.search(re.escape(element.ref) + r"(?![\w-])", references)
    }
    required.update(context.required_observation_refs)
    required.update(item.source_ref for item in context.memory.authorized_transfer_evidence)
    required.update(item.source_ref for item in context.task.verified_link_opens)
    if observation.focused:
        required.add(observation.focused)
    elements_by_ref = {element.ref: element for element in observation.elements}
    ancestors = list(required)
    while ancestors:
        element = elements_by_ref.get(ancestors.pop())
        if element and element.parent_ref and element.parent_ref not in required:
            required.add(element.parent_ref)
            ancestors.append(element.parent_ref)

    empty_observation = observation.model_copy(update={"elements": [], "truncated": True})
    empty_context = context.model_copy(update={"observation": empty_observation})
    used = len(empty_context.model_dump_json(exclude_none=True))
    selected: set[str] = set()
    ranked = rank_observation_for_candidates(
        observation,
        task=context.task.user_goal or context.task.task,
        current_subgoal=context.task.current_subgoal or context.task.task,
    )
    ordered = [element for element in observation.elements if element.ref in required]
    ordered.extend(element for element in ranked.elements if element.ref not in required)

    if used > max_characters:
        raise ContextBudgetExceeded("Required task context exceeds configured limit")
    for element in ordered:
        cost = len(element.model_dump_json(exclude_none=True)) + bool(selected)
        if used + cost > max_characters:
            if element.ref in required:
                raise ContextBudgetExceeded("Required candidate context exceeds configured limit")
            continue
        selected.add(element.ref)
        used += cost

    # Preserve document order and all original element fields. A truncation flag
    # tells the provider it has only part of the page; absence is not proof.
    bounded = empty_observation.model_copy(
        update={"elements": [item for item in observation.elements if item.ref in selected]}
    )
    return context.model_copy(update={"observation": bounded})
