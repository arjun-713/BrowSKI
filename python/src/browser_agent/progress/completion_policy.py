"""User-derived completion constraints that a model plan cannot silently omit."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, cast

from browser_agent._types import SemanticSnapshot, TaskState, VerifiedLinkOpen, WorkingMemory
from browser_agent.decisions.candidates import CandidatePolicy
from browser_agent.decisions.task_recording import candidate_policy_for_recording
from browser_agent.decisions.task_search import task_search_values_by_ref
from browser_agent.decisions.task_values import candidate_policy_for_task_literals
from browser_agent.progress.evidence import (
    advance_observed_milestones,
    local_browser_checks,
    semantic_observation,
)
from browser_agent.progress.link_evidence import (
    required_link_open_checks as required_link_open_checks,
)
from browser_agent.progress.task_state import check_completion


def register_requested_links(task: TaskState, snapshot: SemanticSnapshot) -> None:
    """Remember a bounded initial link group explicitly requested by the user."""
    goal = task.user_goal or task.task
    if task.plan_initialized or task.required_link_refs:
        return
    if not re.search(
        r"\bopen\s+(?:each|every|all)\b[^.!?]{0,120}\b(?:links?|pages?)\b"
        r"[^.!?]{0,80}\b(?:tabs?|tab)\b",
        goal,
        re.I,
    ):
        return
    links = [
        element.ref
        for element in snapshot.elements
        if element.role == "link" and element.visible and element.enabled
    ]
    if 1 <= len(links) <= 8:
        task.required_link_refs = links
        task.required_link_source_tab_id = snapshot.active_tab
        task.required_link_source_generation = snapshot.state_generation
        task.required_link_source_fingerprint = snapshot.page_fingerprint


def record_required_link_open(
    task: TaskState,
    before: SemanticSnapshot,
    after: SemanticSnapshot,
    action: Mapping[str, Any],
) -> VerifiedLinkOpen | None:
    """Bind a required source link to exactly one newly owned browser tab."""
    if action.get("type") != "click":
        return None
    raw_target = action.get("target")
    if not isinstance(raw_target, dict):
        return None
    target = cast(dict[str, Any], raw_target)
    ref = target.get("ref")
    generation = target.get("generation")
    source_tab = task.required_link_source_tab_id
    source_generation = task.required_link_source_generation
    source_fingerprint = task.required_link_source_fingerprint
    if (
        not isinstance(ref, str)
        or ref not in task.required_link_refs
        or not ref.startswith("@")
        or len(ref) > 200
        or not isinstance(generation, int)
        or isinstance(generation, bool)
        or source_tab is None
        or source_tab != before.active_tab
        or source_tab not in after.tabs
        or source_generation is None
        or source_fingerprint is None
        or generation != source_generation
        or before.state_generation != source_generation
        or source_fingerprint != before.page_fingerprint
    ):
        return None

    links = [
        element
        for element in before.elements
        if element.ref == ref
        and element.role.casefold() == "link"
        and element.visible
        and element.enabled
    ]
    if len(links) != 1:
        return None
    new_tabs = list(dict.fromkeys(set(after.tabs) - set(before.tabs)))
    if len(new_tabs) != 1:
        return None

    label = " ".join((links[0].accessible_name or links[0].text or "").split())[:120]
    return VerifiedLinkOpen(
        source_tab_id=source_tab,
        source_ref=ref,
        source_generation=source_generation,
        source_page_fingerprint=source_fingerprint,
        opened_tab_id=new_tabs[0],
        link_label=label,
    )


def requests_confirmation(task: TaskState) -> bool:
    if task.confirmation_received:
        return False
    goal = task.user_goal or task.task
    return bool(
        re.search(
            r"\b(?:get|ask|request|wait|obtain)\b[^.!?]{0,35}"
            r"\b(?:my|user|explicit)\b[^.!?]{0,20}\b(?:confirmation|approval)\b",
            goal,
            re.I,
        )
    )


def outstanding_constraints(
    task: TaskState,
    memory: WorkingMemory,
    snapshot: SemanticSnapshot,
    base_policy: CandidatePolicy | None = None,
) -> list[str]:
    """Require locally authorized values and explicitly requested task effects."""
    observation = semantic_observation(snapshot)
    policy = candidate_policy_for_task_literals(
        task.user_goal or task.task, observation, base_policy
    )
    recording = candidate_policy_for_recording(task, memory, snapshot, observation, policy)
    checks = local_browser_checks(task, snapshot, observation, recording)
    # A general find request authorizes search; it does not require that route.
    optional_search = set(task_search_values_by_ref(task.user_goal or task.task, observation))
    if re.search(r"\bsearch\s+for\b", task.user_goal or task.task, re.I):
        optional_search.clear()
    pending = [
        key
        for key, satisfied in checks.items()
        if not satisfied
        and key.startswith(
            ("field_matches_task:", "selection_matches_task:", "checked_matches_task:")
        )
        and key.removeprefix("field_matches_task:") not in optional_search
    ]
    link_checks = required_link_open_checks(task, snapshot)
    pending.extend(key for key, satisfied in link_checks.items() if not satisfied)
    if memory.record_destination_tab_id == snapshot.active_tab:
        missing_source = [
            element
            for element in observation.elements
            if element.interactable
            and element.name in memory.record_destination_labels
            and element.ref not in recording.values_by_ref
        ]
        if missing_source:
            pending.append(
                "Inspect and select the requested source information before recording it."
            )
    if requests_confirmation(task):
        pending.append("Select the final consequential action so runtime can request confirmation.")
    return pending


def validate_completion_proposal(
    task: TaskState,
    memory: WorkingMemory,
    snapshot: SemanticSnapshot,
    *,
    verified_action: bool,
) -> tuple[bool, list[str]]:
    """Advance observed proof and apply the same gates to every completion path.

    Previously verified milestones remain in working memory. New evidence is
    checked against the current browser snapshot; a model's completion proposal
    never clears user constraints or grants approval.
    """
    if not verified_action:
        return False, ["A recent browser action has not been verified."]

    advance_observed_milestones(task, memory, snapshot)
    pending = outstanding_constraints(task, memory, snapshot)
    for milestone in task.required_milestones:
        evidence = task.milestone_evidence.get(milestone, "")
        for term in re.split(r";|\s+AND\s+", evidence):
            key = term.strip()
            if key.startswith("owned_task_destination:") and key not in task.deterministic_evidence:
                pending.append(key)
    complete = not pending and check_completion(task, snapshot, verified_action=True)
    return complete, pending
