"""Parsing and semantic-field helpers for explicit cross-tab recording."""

from __future__ import annotations

import re
import unicodedata

from browser_agent._types import SemanticElement, SemanticSnapshot, TaskState
from browser_agent.providers.privacy import (
    has_recognized_sensitive_content,
    has_recognized_sensitive_label,
)

_MAX_TASK_CHARS = 8_000
_MAX_LABEL_CHARS = 120
_MAX_VALUE_CHARS = 256
_MAX_RECORD_LABELS = 8
_RECORD_INTENT = re.compile(r"\b(?:record|copy|save|write|enter|put)\b", re.I)
_CROSS_PAGE = re.compile(
    r"\b(?:separate|different|other|multiple)\s+(?:tabs?|pages?)\b"
    r"|\b(?:from|across|between)\s+(?:the\s+)?(?:other\s+)?(?:tabs?|pages?)\b"
    r"|\b(?:tabs?|pages?)\s+from\s+(?:the\s+)?(?:other|source)\b",
    re.I,
)
# Each/every/all page link explicitly assigned to its own or a new tab. This
# does not treat a lone mention of a tab elsewhere in the task as authorization
# for cross-page recording. Keep the clause bounded so unrelated text cannot
# bridge the intent.
_OWN_TAB_CROSS_PAGE = re.compile(
    r"\b(?:each|every|all)\b[^.!?]{0,120}"
    r"\b(?:in|into|on)\s+(?:(?:its|their|a|the)\s+)?"
    r"(?:(?:own|new|separate)\s+)?(?:browser\s+)?tabs?\b",
    re.I,
)
_INSTRUCTION_LIKE = re.compile(
    r"\b(?:ignore|disregard|override)\b.{0,80}\b(?:instructions?|system|user|assistant|previous)\b"
    r"|\b(?:click|navigate|submit|purchase|download)\b.{0,80}\b(?:button|link|page|tab|now|instead)\b",
    re.I,
)
_FIELD_NAMES = frozenset(
    (
        "operating system|model name|product name|item name|manufacturer|specifications|"
        "specification|storage|display|processor|capacity|resolution|battery|memory|weight|"
        "screen|color|price|model|name|ram|size|specs"
    ).split("|")
)
_INPUT_ROLES = {
    "textbox",
    "searchbox",
    "text input",
    "password",
    "passwordbox",
    "credential",
    "combobox",
    "checkbox",
    "radio",
}


def task_text(task: TaskState | str) -> str:
    return (task.user_goal or task.task) if isinstance(task, TaskState) else task


def requested_labels(task: str) -> list[str]:
    if len(task) > _MAX_TASK_CHARS or _RECORD_INTENT.search(task) is None:
        return []
    intent = _RECORD_INTENT.search(task)
    assert intent is not None
    tail = task[intent.end() :]

    candidates: list[tuple[int, str]] = []
    for match in re.finditer(r"[\"']([^\"'\r\n]{1,120})[\"']", tail):
        candidate = clean_label(match.group(1))
        if candidate is not None:
            candidates.append((match.start(), candidate))
    normalized_tail = normalize(tail)
    spans: list[tuple[int, int]] = []
    for label in sorted(_FIELD_NAMES, key=len, reverse=True):
        for match in re.finditer(r"(?<!\w)" + re.escape(label) + r"(?!\w)", normalized_tail):
            if any(match.start() < end and match.end() > start for start, end in spans):
                continue
            candidate = clean_label(label)
            if candidate is not None:
                candidates.append((match.start(), candidate))
                spans.append((match.start(), match.end()))

    if re.search(
        r"\b(?:lowest[- ]priced|cheapest|least expensive)\s+"
        r"(?:matching\s+)?(?:model|product|item|one)\b",
        task,
        re.IGNORECASE,
    ):
        candidates.append((0, "model name"))

    result: list[str] = []
    seen: set[str] = set()
    for _, label in sorted(candidates, key=lambda item: item[0]):
        key = normalize(label)
        if key and key not in seen:
            result.append(label)
            seen.add(key)
        if len(result) >= _MAX_RECORD_LABELS:
            break
    return result


def explicit_record_request(task: str) -> bool:
    return (
        len(task) <= _MAX_TASK_CHARS
        and _RECORD_INTENT.search(task) is not None
        and (_CROSS_PAGE.search(task) is not None or _OWN_TAB_CROSS_PAGE.search(task) is not None)
    )


def clean_label(value: str) -> str | None:
    label = " ".join(value.split()).strip(" .,:;()[]{}")
    if (
        not label
        or len(label) > _MAX_LABEL_CHARS
        or has_recognized_sensitive_label(label)
        or _INSTRUCTION_LIKE.search(label) is not None
        or any(ord(char) < 32 for char in label)
    ):
        return None
    return label


def model_destination_label(
    destination_labels: list[str],
    requested: list[str],
) -> str | None:
    if not any(canonical_destination(item) == "model name" for item in requested):
        return None
    matches = [
        label for label in destination_labels if canonical_destination(label) == "model name"
    ]
    return matches[0] if len(matches) == 1 else None


def observed_destination_labels(
    snapshot: SemanticSnapshot,
    requested: list[str],
) -> list[str]:
    controls: dict[str, list[SemanticElement]] = {}
    elements_by_ref = {element.ref: element for element in snapshot.elements}
    elements_by_ref.update({element.ref: element for element in snapshot.interactive_elements})
    for element in elements_by_ref.values():
        if (
            not element.visible
            or element.visibility.value != "VISIBLE"
            or not element.enabled
            or not element.interactable
            or element.role.casefold() not in {"textbox", "searchbox", "text input"}
            or not element.accessible_name
        ):
            continue
        label = clean_label(element.accessible_name)
        canonical = canonical_destination(label or "")
        if label is None or canonical is None or not destination_field_allowed(label, requested):
            continue
        controls.setdefault(canonical, []).append(element)
    return [
        matches[0].accessible_name
        for matches in controls.values()
        if len(matches) == 1 and matches[0].accessible_name is not None
    ][:_MAX_RECORD_LABELS]


def destination_field_allowed(label: str, requested: list[str]) -> bool:
    if label_requested(label, requested):
        return True
    umbrella = any(canonical_destination(item) == "specifications" for item in requested)
    return (
        umbrella
        and normalize(label) in _FIELD_NAMES
        and canonical_destination(label) != "model name"
    )


def label_requested(label: str, requested: list[str]) -> bool:
    normalized = canonical_destination(label)
    return normalized is not None and any(
        canonical_destination(item) == normalized for item in requested
    )


def canonical_destination(label: str) -> str | None:
    normalized = normalize(label)
    if normalized in {
        "matching model",
        "matching product",
        "model",
        "product name",
        "item name",
        "name",
        "selected model",
    }:
        return "model name"
    if normalized in {"specification", "specs"}:
        return "specifications"
    return normalized or None


def unique_visible_ref(snapshot: SemanticSnapshot, ref: str) -> SemanticElement | None:
    if len(ref) > 200 or not ref.startswith("@"):
        return None
    matches = [
        element
        for element in snapshot.elements
        if element.ref == ref
        and element.visible
        and element.visibility.value == "VISIBLE"
        and element.enabled
        and not element.interactable
        and element.value is None
        and element.role.casefold() not in _INPUT_ROLES
    ]
    return matches[0] if len(matches) == 1 else None


def definition_facts(
    snapshot: SemanticSnapshot,
    requested: list[str],
    destination_labels: list[str],
) -> list[tuple[str, SemanticElement, str]]:
    """Extract named definition facts; never use input values or free-form text."""
    facts: list[tuple[str, SemanticElement, str]] = []
    requested_destinations = {canonical_destination(item) for item in destination_labels}

    for element in snapshot.elements:
        if not _is_visible_fact(element):
            continue
        role = element.role.casefold()
        label = (element.accessible_name or "").strip()
        if role not in {"definition", "description"} or not label:
            continue
        if canonical_destination(label) not in requested_destinations:
            continue
        value = safe_value(element.text)
        clean = clean_label(label)
        if clean is not None and value is not None:
            facts.append((clean, element, value))

    ordered = sorted(snapshot.elements, key=lambda item: item.doc_order)
    for index, term in enumerate(ordered):
        if term.role.casefold() not in {"term", "dt"} or not _is_visible_fact(term):
            continue
        definition = None
        for candidate in ordered[index + 1 :]:
            if (
                candidate.frame != term.frame
                or candidate.frame_path != term.frame_path
                or candidate.ancestry != term.ancestry
            ):
                break
            if candidate.role.casefold() in {"term", "dt"}:
                break
            if candidate.role.casefold() in {"definition", "dd"} and _is_visible_fact(candidate):
                definition = candidate
                break
        if definition is None:
            continue
        raw_label = term.accessible_name or term.text or ""
        clean = clean_label(raw_label)
        value = safe_value(definition.text)
        if clean is None or value is None:
            continue
        canonical = canonical_destination(clean)
        destination = next(
            (label for label in destination_labels if canonical_destination(label) == canonical),
            None,
        )
        if destination is not None and destination_field_allowed(destination, requested):
            facts.append((destination, definition, value))

    deduplicated: list[tuple[str, SemanticElement, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for label, element, value in facts:
        key = (normalize(label), element.ref, value)
        if key not in seen:
            deduplicated.append((label, element, value))
            seen.add(key)
    return deduplicated


def named_text_facts(
    snapshot: SemanticSnapshot,
    requested: list[str],
    destination_labels: list[str],
) -> list[tuple[str, SemanticElement, str]]:
    """Read uniquely named visible text values for explicit destination fields.

    Callers that authorize writes must pass a snapshot already restricted to
    the selected heading's native scope. This helper never reads input values
    and never broadens that scope.
    """
    requested_destinations = {canonical_destination(item) for item in destination_labels}
    facts: list[tuple[str, SemanticElement, str]] = []
    for element in snapshot.elements:
        if not _is_visible_fact(element):
            continue
        if element.role.casefold() not in {"generic", "text", "paragraph"}:
            continue
        label = clean_label(element.accessible_name or "")
        if label is None:
            continue
        canonical = canonical_destination(label)
        destination = next(
            (
                item
                for item in destination_labels
                if canonical_destination(item) == canonical
                and canonical in requested_destinations
                and destination_field_allowed(item, requested)
            ),
            None,
        )
        value = safe_value(element.text)
        if destination is not None and value is not None:
            facts.append((destination, element, value))
    return facts


def _is_visible_fact(element: SemanticElement) -> bool:
    return (
        element.visible
        and element.visibility.value == "VISIBLE"
        and element.enabled
        and not element.interactable
        and element.value is None
        and element.role.casefold() not in _INPUT_ROLES
        and bool(element.ref)
        and len(element.ref) <= 200
        and element.ref.startswith("@")
    )


def safe_value(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = " ".join(value.split())
    if (
        not normalized
        or len(normalized) > _MAX_VALUE_CHARS
        or any(ord(char) < 32 for char in normalized)
        or has_recognized_sensitive_content(normalized)
        or _INSTRUCTION_LIKE.search(normalized) is not None
    ):
        return None
    return normalized


def normalize(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())
