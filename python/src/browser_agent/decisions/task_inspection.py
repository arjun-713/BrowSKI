"""Bounded, untrusted memory of explicitly requested cross-tab inspections."""

from __future__ import annotations

import json
import re
from typing import TypedDict

from browser_agent._types import SemanticElement, SemanticSnapshot, TaskState, WorkingMemory
from browser_agent.decisions.task_record_fields import (
    definition_facts,
    destination_field_allowed,
    explicit_record_request,
    named_text_facts,
    normalize,
    requested_labels,
    safe_value,
    task_text,
)
from browser_agent.providers.privacy import (
    has_recognized_sensitive_content,
    has_recognized_sensitive_label,
)

_INSPECTION_PREFIX = "record_inspection:"
_MAX_INSPECTED_TABS = 8
_MAX_FACTS = 8
_MAX_MEMORY_JSON = 1_000
_PRICE_COMPARISON = re.compile(
    r"\bcompare\b.{0,100}\bprices?\b|\bprice\s+comparison\b"
    r"|\b(?:lowest[- ]priced|cheapest|least expensive)\b",
    re.I,
)
_PRICE_LINE = re.compile(r"^\s*price\s*:\s*(\S(?:.*\S)?)\s*$", re.I)


class _InspectionFact(TypedDict):
    label: str
    value: str
    source_ref: str
    source_generation: int


class _InspectionMemory(TypedDict):
    trust: str
    heading: str
    heading_source_ref: str
    source_generation: int
    facts: list[_InspectionFact]


def remember_record_inspection(
    task: TaskState | str,
    memory: WorkingMemory,
    snapshot: SemanticSnapshot,
) -> bool:
    """Remember safe comparison evidence without authorizing destination writes.

    The destination must have been registered from the initial owned-tab
    snapshot by ``setup_record_targets``. Inspections from other tabs are
    stored in ``acquired_facts`` with explicit untrusted provenance; that map
    is never a source for candidate field values.
    """
    goal = task_text(task)
    destination = memory.record_destination_tab_id
    source = snapshot.active_tab
    if (
        not explicit_record_request(goal)
        or not requested_labels(goal)
        or destination is None
        or destination not in snapshot.tabs
        or source is None
        or source not in snapshot.tabs
        or source == destination
        or not memory.record_destination_labels
        or not any(
            destination_field_allowed(label, requested_labels(goal))
            for label in memory.record_destination_labels
        )
        or len(source) > 200
    ):
        return False

    heading = _unique_heading(snapshot)
    if heading is None:
        return False
    heading_text = safe_value(heading.text)
    if heading_text is None:
        return False

    requested = requested_labels(goal)
    facts = definition_facts(snapshot, requested, memory.record_destination_labels)
    facts.extend(named_text_facts(snapshot, requested, memory.record_destination_labels))
    facts.extend(_price_paragraph_facts(goal, snapshot, requested))
    facts = _unique_facts(facts)
    record: _InspectionMemory = {
        "trust": "untrusted_comparison_only",
        "heading": heading_text,
        "heading_source_ref": heading.ref,
        "source_generation": snapshot.state_generation,
        "facts": [
            {
                "label": label[:120],
                "value": value[:256],
                "source_ref": element.ref,
                "source_generation": snapshot.state_generation,
            }
            for label, element, value in facts[:_MAX_FACTS]
        ],
    }
    encoded = json.dumps(record, ensure_ascii=True, separators=(",", ":"))
    while len(encoded) > _MAX_MEMORY_JSON and record["facts"]:
        record["facts"].pop()
        encoded = json.dumps(record, ensure_ascii=True, separators=(",", ":"))
    if len(encoded) > _MAX_MEMORY_JSON:
        return False

    key = f"{_INSPECTION_PREFIX}{source}"
    if key in memory.acquired_facts:
        del memory.acquired_facts[key]
    _trim_old_inspections(memory)
    memory.remember_fact(key, encoded)
    return True


def _unique_heading(snapshot: SemanticSnapshot) -> SemanticElement | None:
    headings = [
        element
        for element in snapshot.elements
        if element.role.casefold() == "heading"
        and _is_unique_visible_text_element(snapshot, element)
    ]
    return headings[0] if len(headings) == 1 else None


def _is_unique_visible_text_element(
    snapshot: SemanticSnapshot,
    element: SemanticElement,
) -> bool:
    if (
        not element.ref.startswith("@")
        or len(element.ref) > 200
        or not element.visible
        or element.visibility.value != "VISIBLE"
        or not element.enabled
        or element.interactable
        or element.value is not None
        or has_recognized_sensitive_content(element.text or "")
    ):
        return False
    return sum(candidate.ref == element.ref for candidate in snapshot.elements) == 1


def _unique_facts(
    facts: list[tuple[str, SemanticElement, str]],
) -> list[tuple[str, SemanticElement, str]]:
    counts: dict[str, int] = {}
    for label, _, _ in facts:
        key = normalize(label)
        counts[key] = counts.get(key, 0) + 1
    result: list[tuple[str, SemanticElement, str]] = []
    seen: set[tuple[str, str]] = set()
    for label, element, value in facts:
        key = normalize(label)
        if counts[key] != 1 or (key, element.ref) in seen:
            continue
        if has_recognized_sensitive_label(label) or has_recognized_sensitive_content(value):
            continue
        if not element.ref.startswith("@") or len(element.ref) > 200:
            continue
        result.append((label, element, value))
        seen.add((key, element.ref))
    return result


def _price_paragraph_facts(
    goal: str,
    snapshot: SemanticSnapshot,
    requested: list[str],
) -> list[tuple[str, SemanticElement, str]]:
    if (
        not _PRICE_COMPARISON.search(goal)
        or snapshot.viewport.width <= 0
        or snapshot.viewport.height <= 0
    ):
        return []

    matches: list[tuple[str, SemanticElement, str]] = []
    for element in snapshot.elements:
        if not _is_unique_visible_text_element(snapshot, element):
            continue
        if element.role.casefold() not in {"paragraph", "text", "generic"}:
            continue
        if element.bbox is None or not _inside_viewport(element, snapshot):
            continue
        line = _PRICE_LINE.fullmatch(element.text or "")
        if line is None:
            continue
        value = safe_value(line.group(1))
        if value is not None:
            matches.append(("Price", element, value))
    return matches


def _inside_viewport(element: SemanticElement, snapshot: SemanticSnapshot) -> bool:
    box = element.bbox
    if box is None:
        return False
    return (
        box.width > 0
        and box.height > 0
        and box.x >= 0
        and box.y >= 0
        and box.x + box.width <= snapshot.viewport.width
        and box.y + box.height <= snapshot.viewport.height
    )


def _trim_old_inspections(memory: WorkingMemory) -> None:
    keys = [key for key in memory.acquired_facts if key.startswith(_INSPECTION_PREFIX)]
    while len(keys) >= _MAX_INSPECTED_TABS:
        oldest = keys.pop(0)
        del memory.acquired_facts[oldest]
