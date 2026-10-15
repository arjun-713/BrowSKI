"""Candidate assembly and local action-binding helpers for Luna."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from browser_agent._types import (
    AgentObservation,
    BrowserAction,
    ElementRef,
    SemanticSnapshot,
    TaskState,
    WorkingMemory,
)
from browser_agent.decisions import ActionCandidate, CandidatePolicy, build_action_candidates
from browser_agent.decisions.candidate_ranking import rank_observation_for_candidates
from browser_agent.decisions.task_recording import candidate_policy_for_recording
from browser_agent.decisions.task_sites import destination_task, requested_sites
from browser_agent.decisions.task_tabs import MAX_OWNED_TABS, with_owned_tab_candidates
from browser_agent.decisions.task_transfers import candidate_policy_for_authorized_transfers
from browser_agent.decisions.task_values import candidate_policy_for_task_literals
from browser_agent.progress.completion_policy import required_link_open_checks
from browser_agent.progress.evidence import semantic_observation


def action_candidates(
    *,
    snapshot: SemanticSnapshot,
    task: TaskState,
    memory: WorkingMemory,
    observation: AgentObservation,
    candidate_policy: CandidatePolicy,
    owned_tab_urls: list[str] | None = None,
    task_tab_labels: Mapping[str, str] | None = None,
    site_aliases: Mapping[str, str] | None = None,
) -> list[ActionCandidate]:
    """Build the one finite set used for every executable Luna decision."""
    goal = task.user_goal or task.task
    policy = candidate_policy_for_task_literals(goal, observation, candidate_policy)
    policy = candidate_policy_for_authorized_transfers(
        goal,
        memory,
        snapshot,
        observation,
        policy,
    )
    policy = candidate_policy_for_recording(task, memory, snapshot, observation, policy)
    ranking_target = task.current_subgoal or task.next_milestone or task.task
    link_checks = required_link_open_checks(task, snapshot)
    completed_link_refs = {
        key.removeprefix("required_link_open:") for key, is_open in link_checks.items() if is_open
    }
    candidate_observation = observation.model_copy(
        update={
            "elements": [
                element
                for element in observation.elements
                if element.ref not in completed_link_refs
            ]
        }
    )
    pending_link_refs = [
        key.removeprefix("required_link_open:")
        for key, is_open in link_checks.items()
        if not is_open
    ]
    # Required links are opened into owned tabs by this workflow. A source
    # link click can itself create a tab (for example, target="_blank"), so
    # apply the same bound here as for explicit new-tab candidates.
    if len(set(snapshot.tabs)) >= MAX_OWNED_TABS:
        blocked_link_refs = set(pending_link_refs)
        pending_link_refs = []
        candidate_observation = candidate_observation.model_copy(
            update={
                "elements": [
                    element
                    for element in candidate_observation.elements
                    if element.ref not in blocked_link_refs
                ]
            }
        )
    candidates = build_action_candidates(
        goal,
        ranking_target,
        rank_observation_for_candidates(
            candidate_observation,
            task=goal,
            current_subgoal=ranking_target,
            priority_refs=pending_link_refs,
        ),
        {"click", "check", "scroll", "type", "select"},
        policy,
    )
    return with_owned_tab_candidates(
        candidates,
        task=destination_task(goal, requested_sites(goal, site_aliases or {})),
        snapshot=snapshot,
        max_candidates=candidate_policy.max_candidates,
        owned_tab_urls=owned_tab_urls or [],
        task_tab_labels=task_tab_labels,
    )


def candidate_options(candidates: list[ActionCandidate]) -> dict[str, str]:
    # Task and subgoal already have dedicated typed fields in ReasoningContext.
    # Repeating them in every option wastes input tokens and can truncate the
    # actual action description on longer tasks.
    return {
        f"c{index:02d}": (
            candidate.description.partition("; action: ")[2]
            if candidate.description.startswith("Task: ") and "; action: " in candidate.description
            else candidate.description
        )
        for index, candidate in enumerate(candidates, start=1)
    }


def agent_observation(snapshot: SemanticSnapshot) -> AgentObservation:
    return semantic_observation(snapshot)


def resolve_target(
    candidate: ActionCandidate,
    snapshot: SemanticSnapshot,
) -> ElementRef | None:
    if candidate.target_ref is None:
        return None
    element = snapshot.by_ref(candidate.target_ref)
    if element is None or not element.interactable or not element.visible or not element.enabled:
        return None
    return ElementRef(
        ref=element.ref,
        id=element.id,
        generation=snapshot.state_generation,
    )


def action_signature(action: BrowserAction) -> dict[str, Any]:
    """Compare semantic targets without trusting model-supplied registry IDs."""
    signature = action.model_dump(mode="json", exclude_none=True)
    if action.target is not None:
        signature["target"] = {
            "ref": action.target.ref,
            "generation": action.target.generation,
        }
    return signature
