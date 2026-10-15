"""Extract task-authored values and match them to unique text controls."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable

from browser_agent._types import AgentObservation, PrunedElement

MAX_TASK_CHARS = 8_000

MAX_ENTITY_MATCHES = 8

MAX_VALUE_CHARS = 256

MAX_FIELD_CHARS = 120

FIELD_FILLERS = {
    "a",
    "an",
    "appointment",
    "preferred",
    "registration",
    "reservation",
    "the",
    "travel",
    "trip",
    "workshop",
    "workspace",
}

FIELD_ALIASES = {
    "day": {"day"},
    "date": {"date"},
    "start": {"start", "starts", "begin", "begins", "from"},
    "end": {"end", "ends", "finish", "finishes", "until", "to"},
}

_TEXT_ROLES = {"textbox", "text input"}

_ORGANIZATION_SUFFIXES = {
    "co",
    "company",
    "corp",
    "corporation",
    "foundation",
    "group",
    "inc",
    "incorporated",
    "labs",
    "limited",
    "llc",
    "ltd",
    "studio",
    "university",
}

_EMAIL = re.compile(
    r"(?<![\w.+-])"
    r"[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+"
    r"@(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+"
    r"[A-Z]{2,63}(?![\w-])",
    re.IGNORECASE,
)

_NAME_TOKEN = r"[A-ZÀ-ÖØ-Þ][\w'’\-À-ÖØ-öø-ÿ]*"

_PERSON_ANCHORS = re.compile(
    rf"(?i:\b(?:registration\s+for|register\s+for|register|reservation\s+for|"
    rf"reserve\s+(?:a\s+)?(?:seat\s+)?for|seat\s+for)\s+)"
    rf"(?P<name>{_NAME_TOKEN}(?:\s+{_NAME_TOKEN}){{1,3}})"
    r"(?=\s+(?:and|at|for|on|then|with)\b|[,;.!?:]|$)",
)

_ORGANIZATION = re.compile(
    r"\b(?:organization|organisation|company|employer)\s+"
    r"(?:is\s+|as\s+)?(?P<value>[^,;.!?\r\n]{1,96}?)"
    r"(?=\s+(?:at|by|for|from|in|on|with)\s+|[,;.!?\r\n]|$)",
    re.IGNORECASE,
)


def collect_entity(
    literals: list[str],
    controls: list[PrunedElement],
    derived: dict[str, set[str]],
) -> None:
    if len(literals) != 1 or len(controls) != 1:
        return
    value = literals[0].strip()
    if value and len(value) <= MAX_VALUE_CHARS:
        derived.setdefault(controls[0].ref, set()).add(value)


def person_names(task: str) -> list[str]:
    return _unique_literals(
        [match.group("name").strip() for match in _PERSON_ANCHORS.finditer(task)]
    )


def emails(task: str) -> list[str]:
    return _unique_literals([match.group(0) for match in _EMAIL.finditer(task)])


def organizations(task: str) -> list[str]:
    explicit = [
        value
        for match in _ORGANIZATION.finditer(task)
        if (value := match.group("value").strip())
        and not re.search(r"\b(?:and|click|fill|open|save|select|then)\b", value, re.I)
    ]
    return _unique_literals(explicit + _comma_adjacent_organizations(task))


def _comma_adjacent_organizations(task: str) -> list[str]:
    values: list[str] = []
    for email in _EMAIL.finditer(task):
        remainder = task[email.end() :]
        match = re.match(
            r"\s*,\s*(?P<value>[^,;.!?\r\n]{1,96}?)"
            r"(?=\s+(?:for|on|with)\s+|[,;.!?\r\n]|$)",
            remainder,
            re.IGNORECASE,
        )
        if not match:
            continue
        value = match.group("value").strip()
        if re.match(r"(?:organization|organisation|company|employer)\b", value, re.I):
            continue
        if _has_organization_suffix(value):
            values.append(value)
    return values


def _has_organization_suffix(value: str) -> bool:
    words = normalize(value).split()
    return bool(words and words[-1].rstrip(".,") in _ORGANIZATION_SUFFIXES)


def matching_text_controls(
    observation: AgentObservation,
    predicate: Callable[[str], bool],
) -> list[PrunedElement]:
    matches = [
        element
        for element in observation.elements
        if element.interactable
        and element.role.casefold() in _TEXT_ROLES
        and element.name
        and predicate(element.name)
    ]
    return unique_refs(matches)


def is_person_name(label: str) -> bool:
    words = set(normalize(label).split())
    if "name" not in words:
        return False
    excluded = {
        "account",
        "business",
        "company",
        "group",
        "organization",
        "organisation",
        "product",
        "project",
        "team",
        "user",
        "username",
        "workspace",
    }
    return not words.intersection(excluded)


def is_email_field(label: str) -> bool:
    return bool(re.search(r"\b(?:e[ -]?mail)\b", label, re.IGNORECASE))


def is_organization_field(label: str) -> bool:
    return bool(
        re.search(
            r"\b(?:organization|organisation|company|employer)\b",
            label,
            re.IGNORECASE,
        )
    )


def unique_refs(elements: list[PrunedElement]) -> list[PrunedElement]:
    by_ref: dict[str, PrunedElement] = {}
    for element in elements:
        by_ref.setdefault(element.ref, element)
    return list(by_ref.values())


def trim_value(value: str) -> str:
    return value.strip().strip("\"'").strip()


def _unique_literals(values: list[str]) -> list[str]:
    by_normalized: dict[str, str] = {}
    for value in values:
        stripped = value.strip().strip("\"'").strip()
        if stripped and len(stripped) <= MAX_VALUE_CHARS:
            by_normalized.setdefault(normalize(stripped), stripped)
    return list(by_normalized.values())


def normalize(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(normalized.split())
