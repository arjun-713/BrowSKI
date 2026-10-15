"""Extract conservative, user-authored form literals from task instructions."""

from __future__ import annotations

from dataclasses import replace

from browser_agent._types import AgentObservation
from browser_agent.decisions.candidates import CandidatePolicy
from browser_agent.decisions.checkbox_intents import checkbox_requests, matching_checkbox
from browser_agent.decisions.entity_literals import (
    MAX_TASK_CHARS,
    collect_entity,
    emails,
    is_email_field,
    is_organization_field,
    is_person_name,
    matching_text_controls,
    normalize,
    organizations,
    person_names,
)
from browser_agent.decisions.selection_intents import (
    matching_combobox,
    selection_requests,
    unique_task_named_option,
)


def candidate_policy_for_task_entities(
    task: str,
    observation: AgentObservation,
    base_policy: CandidatePolicy | None = None,
) -> CandidatePolicy:
    """Add task-authored values and selections grounded in unique controls."""
    policy = base_policy or CandidatePolicy()
    if not task.strip() or len(task) > MAX_TASK_CHARS:
        return policy

    values = dict(policy.values_by_ref)
    derived_values: dict[str, set[str]] = {}
    for literals, predicate in (
        (person_names(task), is_person_name),
        (emails(task), is_email_field),
        (organizations(task), is_organization_field),
    ):
        collect_entity(literals, matching_text_controls(observation, predicate), derived_values)
    for ref, requested_values in derived_values.items():
        if ref not in values and len(requested_values) == 1:
            values[ref] = next(iter(requested_values))

    select_labels = dict(policy.select_labels_by_ref)
    by_ref: dict[str, set[str]] = {}
    blocked_refs: set[str] = set()
    for field_name, option_text in selection_requests(task, observation):
        control = matching_combobox(field_name, observation)
        if control is None:
            continue
        option = unique_task_named_option(option_text, task, observation, control)
        if option is None:
            blocked_refs.add(control.ref)
        else:
            by_ref.setdefault(control.ref, set()).add(option)
    for ref, options in by_ref.items():
        normalized = {normalize(option) for option in options}
        if ref not in select_labels and ref not in blocked_refs and len(normalized) == 1:
            select_labels[ref] = (sorted(options, key=normalize)[0],)

    checked = dict(policy.checked_by_ref)
    checkbox_intents: dict[str, set[bool]] = {}
    for requested, should_check in checkbox_requests(task):
        control = matching_checkbox(requested, observation)
        if control is not None:
            checkbox_intents.setdefault(control.ref, set()).add(should_check)
    for ref, intents in checkbox_intents.items():
        if ref not in checked and len(intents) == 1:
            checked[ref] = next(iter(intents))

    if (
        values == policy.values_by_ref
        and select_labels == policy.select_labels_by_ref
        and checked == policy.checked_by_ref
    ):
        return policy
    return replace(
        policy,
        values_by_ref=values,
        select_labels_by_ref=select_labels,
        checked_by_ref=checked,
    )
