"""Derive finite input values only from explicit quoted user instructions."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import replace

from browser_agent._types import AgentObservation
from browser_agent.decisions.candidates import CandidatePolicy

_MAX_TASK_CHARS = 8_000
_MAX_BINDINGS = 8
_MAX_LABEL_CHARS = 120
_MAX_VALUE_CHARS = 256


def candidate_policy_for_task_literals(
    task: str,
    observation: AgentObservation,
    base_policy: CandidatePolicy | None = None,
) -> CandidatePolicy:
    """Merge explicit task literals into a policy without trusting page text.

    Supported forms are ``set "Field" to "Value"``,
    ``fill "Field" with "Value"``, and ``type "Value" into "Field"``.
    Labels must match exactly, after case and whitespace normalization, to one
    interactable semantic text input's accessible name.
    """
    policy = base_policy or CandidatePolicy()
    if len(task) > _MAX_TASK_CHARS:
        return policy

    parsed = _parse_bindings(task)
    if not parsed:
        return policy

    by_label: dict[str, str | None] = {}
    for label, value in parsed:
        normalized_label = _normalize(label)
        if not normalized_label or not value.strip():
            continue
        if normalized_label in by_label and by_label[normalized_label] != value:
            by_label[normalized_label] = None
        else:
            by_label[normalized_label] = value

    derived: dict[str, str] = {}
    for label, value in by_label.items():
        if value is None:
            continue
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

    if not derived:
        return policy
    values = dict(policy.values_by_ref)
    values.update(derived)
    return replace(policy, values_by_ref=values)


def _parse_bindings(task: str) -> list[tuple[str, str]]:
    bindings: list[tuple[str, str]] = []
    for pattern in _patterns():
        for match in pattern.finditer(task):
            label = match.group("field").strip()
            value = match.group("value")
            if not label or not value.strip():
                continue
            bindings.append((label, value))
            if len(bindings) > _MAX_BINDINGS:
                return []
    return bindings


def _patterns() -> tuple[re.Pattern[str], ...]:
    # Exclude the active quote from each capture using a lookahead, while
    # allowing the other quote style inside a value such as "O'Reilly".
    field = (
        r'(?P<field_quote>["\'])(?P<field>'
        rf"(?:(?!(?P=field_quote))[^\r\n]){{1,{_MAX_LABEL_CHARS}}}?)(?P=field_quote)"
    )
    value = (
        r'(?P<value_quote>["\'])(?P<value>'
        rf"(?:(?!(?P=value_quote))[^\r\n]){{1,{_MAX_VALUE_CHARS}}}?)(?P=value_quote)"
    )
    return (
        re.compile(r"\bset\s+" + field + r"\s+to\s+" + value, re.IGNORECASE),
        re.compile(r"\bfill\s+" + field + r"\s+with\s+" + value, re.IGNORECASE),
        re.compile(r"\btype\s+" + value + r"\s+into\s+" + field, re.IGNORECASE),
    )


def _normalize(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(normalized.split())
