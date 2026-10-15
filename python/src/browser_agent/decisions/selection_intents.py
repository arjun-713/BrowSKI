"""Bind user-requested select values to observed option/control pairs."""

from __future__ import annotations

import re

from browser_agent._types import AgentObservation, PrunedElement
from browser_agent.decisions.entity_literals import (
    FIELD_ALIASES,
    FIELD_FILLERS,
    MAX_ENTITY_MATCHES,
    MAX_FIELD_CHARS,
    MAX_TASK_CHARS,
    normalize,
    trim_value,
    unique_refs,
)

_EXPLICIT_VALUE = re.compile(
    r"\b(?:set|change|switch)\s+(?:the\s+)?"
    r"(?P<field>[^,;.!?\r\n]{1,120}?)\s+(?:to|as)\s+"
    r"(?P<value>[^,;.!?\r\n]{1,120}?)"
    r"(?=$|[,;.!?]|\s+(?:and|then)\b)",
    re.IGNORECASE,
)

_EXPLICIT_SELECTION = re.compile(
    r"\b(?:select|choose|pick)\s+(?:the\s+)?"
    r"(?P<value>[^,;.!?\r\n]{1,120}?)\s+(?:in|from|for)\s+"
    r"(?:the\s+)?(?P<field>[^,;.!?\r\n]{1,120}?)"
    r"(?=$|[,;.!?]|\s+(?:and|then)\b)",
    re.IGNORECASE,
)

_INTERVAL = re.compile(
    r"\bfrom\s+(?P<start>[^,;.!?\r\n]{1,80}?)\s+"
    r"(?:until|to)\s+(?P<end>[^,;.!?\r\n]{1,80}?)"
    r"(?=$|[,;.!?]|\s+(?:and|then)\b)",
    re.IGNORECASE,
)

_NEGATED_ACTION = re.compile(
    r"\b(?:do\s+not|don't|never|avoid|exclude)\s+"
    r"(?:select|choose|pick|set|change|switch|use|schedule|create|book)\b",
    re.IGNORECASE,
)

_NEGATED_ON = re.compile(r"\b(?:not|never|avoid|except)\s+on\s+$", re.IGNORECASE)
_NEGATED_WEEKDAY = re.compile(
    r"\b(?:do\s+not|don't|never|avoid|exclude)\b(?:\s+\w+){0,6}\s+$",
    re.IGNORECASE,
)


def selection_requests(task: str, observation: AgentObservation) -> list[tuple[str, str]]:
    if len(task) > MAX_TASK_CHARS:
        return []
    options = _observed_option_labels(observation)
    requests: list[tuple[str, str]] = []
    for match in _EXPLICIT_VALUE.finditer(task):
        if _is_negated(task, match.start()):
            continue
        field = _trim_field(match.group("field"))
        value = trim_value(match.group("value"))
        if field and value:
            requests.append((field, value))
    for match in _EXPLICIT_SELECTION.finditer(task):
        if _is_negated(task, match.start()):
            continue
        field = _trim_field(match.group("field"))
        value = trim_value(match.group("value"))
        if field and value:
            requests.append((field, value))

    for match in _INTERVAL.finditer(task):
        if _is_negated(task, match.start()):
            continue
        start = trim_value(match.group("start"))
        end = trim_value(match.group("end"))
        if _task_mentions_option(start, task, options):
            requests.append(("start", start))
        if _task_mentions_option(end, task, options):
            requests.append(("end", end))

    for option in options:
        if not _task_mentions_option(option, task, options):
            continue
        pattern = rf"\bon\s+{re.escape(option)}(?=$|[\s,;.!?])"
        for match in re.finditer(pattern, task, re.IGNORECASE):
            prefix = task[max(0, match.start() - 32) : match.start()]
            if not _NEGATED_ON.search(prefix) and not _NEGATED_WEEKDAY.search(prefix):
                requests.append((_field_for_date_or_day(option), option))

    # Tasks commonly phrase the weekday as an adjective ("a Wednesday
    # session") rather than "on Wednesday". Bind it only when the observed
    # Day control and the option are both unique.
    day_control = matching_combobox("day", observation)
    if day_control is not None:
        for option in options:
            if not _looks_like_weekday(option) or not _task_mentions_option(option, task, options):
                continue
            position = task.casefold().find(option.casefold())
            prefix = task[max(0, position - 48) : position]
            if _is_negated(task, position) or _NEGATED_WEEKDAY.search(prefix):
                continue
            if unique_task_named_option(option, task, observation, day_control) is not None:
                if not any(
                    normalize(field) == normalize(day_control.name or "Day")
                    and normalize(value) == normalize(option)
                    for field, value in requests
                ):
                    requests.append((day_control.name or "Day", option))

    # A task may name a choice without naming its control. Permit that only
    # when the page exposes a single unique combobox and a single matching
    # option. If several controls exist, ownership must be explicit.
    if not requests:
        named = [option for option in options if _task_mentions_option(option, task, options)]
        for option in named:
            owners = _option_owners(option, observation)
            if len(owners) == 1:
                requests.append((owners[0].name or "", option))
        if not requests:
            controls = unique_refs(
                [
                    element
                    for element in observation.elements
                    if element.interactable
                    and element.role.casefold() == "combobox"
                    and element.name
                ]
            )
            if len(controls) == 1:
                requests.extend((controls[0].name or "", option) for option in named)

    if len(requests) > MAX_ENTITY_MATCHES:
        return []
    return requests


def _observed_option_labels(observation: AgentObservation) -> list[str]:
    labels: list[str] = []
    for element in observation.elements:
        if element.role.casefold() != "option":
            continue
        label = (element.name or element.text or "").strip()
        if label and len(label) <= MAX_FIELD_CHARS:
            labels.append(label)
    return list(dict.fromkeys(labels))


def _task_mentions_option(value: str, task: str, options: list[str]) -> bool:
    if not any(normalize(value) == normalize(option) for option in options):
        return False
    pattern = rf"(?<!\w){re.escape(value)}(?!\w)"
    return re.search(pattern, task, re.IGNORECASE) is not None


def unique_task_named_option(
    requested: str,
    task: str,
    observation: AgentObservation,
    control: PrunedElement | None = None,
) -> str | None:
    if not _task_mentions_option(requested, task, _observed_option_labels(observation)):
        return None
    matches = [
        element
        for element in observation.elements
        if element.role.casefold() == "option"
        and normalize(element.name or element.text or "") == normalize(requested)
    ]
    grouped = [
        element
        for element in observation.elements
        if element.role.casefold() == "option" and element.parent_ref
    ]
    if grouped:
        if control is None:
            return None
        matches = [element for element in matches if element.parent_ref == control.ref]
    matches = unique_refs(matches)
    if len(matches) != 1:
        return None
    return (matches[0].name or matches[0].text or "").strip() or None


def matching_combobox(field_name: str, observation: AgentObservation) -> PrunedElement | None:
    controls = unique_refs(
        [
            element
            for element in observation.elements
            if element.interactable and element.role.casefold() == "combobox" and element.name
        ]
    )
    requested = normalize(_trim_field(field_name))
    if not requested:
        return None
    exact = [element for element in controls if normalize(element.name or "") == requested]
    if len(exact) == 1:
        return exact[0]
    if exact:
        return None

    terms = set(requested.split()) - FIELD_FILLERS
    if not terms:
        return None
    matches = [
        element
        for element in controls
        if terms.issubset(set(normalize(element.name or "").split()) - FIELD_FILLERS)
    ]
    if len(matches) == 1:
        return matches[0]
    if len(terms) == 1:
        aliases = FIELD_ALIASES.get(next(iter(terms)), terms)
        matching_terms = [
            element
            for element in controls
            if aliases.intersection(set(normalize(element.name or "").split()))
        ]
        if len(matching_terms) == 1:
            return matching_terms[0]
    return None


def _field_for_date_or_day(option: str) -> str:
    if _looks_like_calendar_date(option):
        return "date"
    if _looks_like_weekday(option):
        return "day"
    return "day"


def _option_owners(option: str, observation: AgentObservation) -> list[PrunedElement]:
    controls = {
        element.ref: element
        for element in observation.elements
        if element.role.casefold() == "combobox"
    }
    matches = [
        element
        for element in observation.elements
        if element.role.casefold() == "option"
        and normalize(element.name or element.text or "") == normalize(option)
    ]
    grouped = [
        element
        for element in observation.elements
        if element.role.casefold() == "option" and element.parent_ref
    ]
    if grouped:
        owners = [
            controls[element.parent_ref] for element in matches if element.parent_ref in controls
        ]
        return unique_refs(owners)
    return []


def _looks_like_weekday(value: str) -> bool:
    return normalize(value).rstrip(".,") in {
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
    }


def _looks_like_calendar_date(value: str) -> bool:
    cleaned = normalize(value).strip(".,")
    month = (
        r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
        r"jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?"
    )
    return bool(
        re.fullmatch(rf"(?:{month})\s+\d{{1,2}}(?:st|nd|rd|th)?", cleaned)
        or re.fullmatch(rf"\d{{1,2}}\s+(?:{month})", cleaned)
        or re.fullmatch(r"\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?", cleaned)
    )


def _trim_field(value: str) -> str:
    trimmed = value.strip().strip("\"'").strip()
    trimmed = re.sub(r"\s+(?:dropdown|combobox)$", "", trimmed, flags=re.IGNORECASE)
    return re.sub(r"^(?:the|a|an)\s+", "", trimmed, flags=re.IGNORECASE).strip()


def _is_negated(task: str, action_start: int) -> bool:
    clause_start = max(task.rfind(mark, 0, action_start) for mark in ".,;!?\n") + 1
    return _NEGATED_ACTION.search(task[clause_start:action_start]) is not None
