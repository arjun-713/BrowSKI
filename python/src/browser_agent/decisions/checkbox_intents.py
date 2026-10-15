"""Infer explicit checkbox requests from unique label vocabulary."""

from __future__ import annotations

import re

from browser_agent._types import AgentObservation, PrunedElement
from browser_agent.decisions.entity_literals import (
    MAX_ENTITY_MATCHES,
    MAX_FIELD_CHARS,
    normalize,
    trim_value,
    unique_refs,
)

_CHECKBOX_INTENT = re.compile(
    r"\b(?P<negative>do\s+not\s+include|don't\s+include|exclude|"
    r"leave\s+off|uncheck|opt\s+out\s+of|disable)\s+"
    r"(?P<items>[^,;.!?\r\n]{1,120}?)"
    r"(?=$|[,;.!?]|\s+then\b)|"
    r"\b(?P<positive>include|ask\s+for|request|opt\s+in\s+to|"
    r"check|tick|enable)\s+"
    r"(?P<positive_items>[^,;.!?\r\n]{1,120}?)"
    r"(?=$|[,;.!?]|\s+then\b)",
    re.IGNORECASE,
)


def checkbox_requests(task: str) -> list[tuple[str, bool]]:
    requests: list[tuple[str, bool]] = []
    for match in _CHECKBOX_INTENT.finditer(task):
        is_negative = match.group("negative") is not None
        items = match.group("items") if is_negative else match.group("positive_items")
        for item in re.split(r"\s+(?:and|also)\s+", items or "", flags=re.IGNORECASE):
            item = trim_value(item)
            if item and len(item) <= MAX_FIELD_CHARS:
                requests.append((item, not is_negative))
    return requests if len(requests) <= MAX_ENTITY_MATCHES else []


def matching_checkbox(requested: str, observation: AgentObservation) -> PrunedElement | None:
    requested_terms = _intent_terms(requested)
    if not requested_terms:
        return None
    scored: list[tuple[int, PrunedElement]] = []
    for element in observation.elements:
        if not element.interactable or element.role.casefold() != "checkbox" or not element.name:
            continue
        overlap = len(requested_terms & _intent_terms(element.name))
        threshold = 1 if len(requested_terms) == 1 else 2
        if overlap >= threshold:
            scored.append((overlap, element))
    if not scored:
        return None
    highest = max(score for score, _ in scored)
    matches = unique_refs([element for score, element in scored if score == highest])
    return matches[0] if len(matches) == 1 else None


def _intent_terms(value: str) -> set[str]:
    ignored = {
        "a",
        "an",
        "and",
        "for",
        "of",
        "the",
        "to",
        "with",
        "me",
        "my",
        "please",
        "receive",
        "opt",
        "in",
        "out",
    }
    terms: set[str] = set()
    for word in re.findall(r"[\w]+", normalize(value)):
        if word in ignored:
            continue
        if word.endswith("ies") and len(word) > 4:
            word = word[:-3] + "y"
        elif word.endswith("s") and len(word) > 3:
            word = word[:-1]
        terms.add(word)
    return terms
