"""Derive finite input values from explicit task instructions and search intent."""

from __future__ import annotations

import re
from dataclasses import replace

from browser_agent._types import AgentObservation
from browser_agent.decisions.candidates import CandidatePolicy
from browser_agent.decisions.task_commands import user_commands
from browser_agent.decisions.task_entities import candidate_policy_for_task_entities
from browser_agent.decisions.task_search import task_search_values_by_ref
from browser_agent.task_literals import MAX_BINDINGS as _MAX_BINDINGS
from browser_agent.task_literals import normalize_field_label as _normalize
from browser_agent.task_literals import quoted_field_values

_MAX_TASK_CHARS = 8_000
_SELECT_INTENT = re.compile(
    r"\b(?:select|choose)\s+(?P<value>[^\r\n,.;]{1,120}?)\s+"
    r"(?:in|from)\s+(?P<field>[^\r\n,.;]{1,120}?)"
    r"(?:\s+(?:dropdown|combobox))?(?=$|[,.;\r\n])",
    re.IGNORECASE,
)


def candidate_policy_for_task_literals(
    task: str,
    observation: AgentObservation,
    base_policy: CandidatePolicy | None = None,
) -> CandidatePolicy:
    """Merge explicit task literals into a policy without trusting page text.

    Supported input forms are ``set "Field" to "Value"``,
    ``fill "Field" with "Value"``, and ``type "Value" into "Field"``.
    Selection intent supports ``select Value in Field dropdown`` and
    ``choose Value from Field``. Search intent supports ``search for``,
    ``find``, and ``buy`` phrases bound to a unique observed search control.
    Labels match one observed semantic control; a selection value must also
    match one observed option label or value.
    """
    policy = candidate_policy_for_task_entities(task, observation, base_policy)
    if len(task) > _MAX_TASK_CHARS:
        return policy

    by_label = quoted_field_values(task)
    select_intents = _parse_select_intents(task)

    derived: dict[str, str] = {}
    for label, value in by_label.items():
        matches = [
            element
            for element in observation.elements
            if element.interactable
            and element.role.casefold() in {"textbox", "searchbox", "text input"}
            and element.name is not None
            and _normalize(element.name) == label
        ]
        if len(matches) != 1:
            continue
        ref = matches[0].ref
        if ref not in policy.values_by_ref:
            derived[ref] = value

    select_labels = _derive_select_labels(select_intents, observation, policy)
    checks = dict(policy.checked_by_ref)
    for command in user_commands(task, observation) or ():
        if command.kind == "type" and command.value is not None:
            if command.ref not in policy.values_by_ref and command.ref not in derived:
                derived[command.ref] = command.value
        elif command.kind == "select" and command.value is not None:
            if command.ref not in policy.select_values_by_ref:
                select_labels.setdefault(command.ref, (command.value,))
        elif command.kind == "check" and command.checked is not None:
            checks.setdefault(command.ref, command.checked)
    search_values = task_search_values_by_ref(
        task,
        observation,
        excluded_refs=set(policy.values_by_ref) | set(derived),
    )
    if not derived and not select_labels and not search_values and checks == policy.checked_by_ref:
        return policy

    values = dict(policy.values_by_ref)
    values.update(derived)
    values.update(search_values)
    labels_by_ref = dict(policy.select_labels_by_ref)
    labels_by_ref.update(select_labels)
    return replace(
        policy,
        values_by_ref=values,
        select_labels_by_ref=labels_by_ref,
        checked_by_ref=checks,
    )


def _parse_select_intents(task: str) -> list[tuple[str, str]]:
    intents: list[tuple[str, str]] = []
    for match in _SELECT_INTENT.finditer(task):
        value = match.group("value").strip().strip("\"'").strip()
        label = match.group("field").strip().strip("\"'").strip()
        if not value or not label:
            continue
        intents.append((label, value))
        if len(intents) > _MAX_BINDINGS:
            return []
    return intents


def _derive_select_labels(
    intents: list[tuple[str, str]],
    observation: AgentObservation,
    policy: CandidatePolicy,
) -> dict[str, tuple[str, ...]]:
    by_field: dict[str, tuple[set[str], set[str]]] = {}
    for field_label, option_value in intents:
        normalized_field = _normalize(field_label)
        normalized_value = _normalize(option_value)
        if not normalized_field or not normalized_value:
            continue
        canonical_field = _normalize(re.sub(r"^(?:the|a|an)\s+", "", field_label, flags=re.I))
        labels, values = by_field.setdefault(canonical_field, (set(), set()))
        labels.add(normalized_field)
        values.add(option_value)

    derived: dict[str, list[str]] = {}
    for field_label, (field_labels, requested_values) in by_field.items():
        if len({_normalize(value) for value in requested_values}) != 1:
            continue
        requested_value = next(iter(requested_values))
        comboboxes = [
            element
            for element in observation.elements
            if element.interactable
            and element.role.casefold() == "combobox"
            and element.name is not None
            and _normalize(element.name) in field_labels
        ]
        if not comboboxes:
            # Prefer exact accessible-name matches; only drop a leading article
            # when none of the explicitly named labels exists in the snapshot.
            comboboxes = [
                element
                for element in observation.elements
                if element.interactable
                and element.role.casefold() == "combobox"
                and element.name is not None
                and _normalize(element.name) == field_label
            ]
        if len(comboboxes) != 1:
            continue

        matching_options = [
            element
            for element in observation.elements
            if element.role.casefold() == "option"
            and (element.parent_ref is None or element.parent_ref == comboboxes[0].ref)
            and any(
                candidate is not None and _normalize(candidate) == _normalize(requested_value)
                for candidate in (element.name, element.text, element.value)
            )
        ]
        if len(matching_options) != 1:
            continue

        option = matching_options[0]
        option_label = option.name or option.text or option.value
        if not option_label:
            continue
        ref = comboboxes[0].ref
        if ref in policy.select_labels_by_ref:
            continue
        derived.setdefault(ref, []).append(option_label)

    return {ref: tuple(dict.fromkeys(labels)) for ref, labels in derived.items()}
