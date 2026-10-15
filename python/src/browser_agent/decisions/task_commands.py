"""Bind explicit user commands to unique observed controls without model values."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from browser_agent._types import AgentObservation, PrunedElement

CommandKind = Literal["click", "type", "select", "check"]
_VERBS = (
    "click|tap|press|fill|set|type|enter|select|choose|change|check|uncheck|"
    "enable|disable|turn|switch|archive|restore|open|continue|save|submit|"
    "send|delete|publish|pin|apply|refresh|confirm|increment|finish|stop"
)
_SEPARATOR = re.compile(rf"(?:\s*,?\s+(?:and\s+then|and|then)\s+|,\s*)(?=(?:{_VERBS})\b)", re.I)
_TEXT_ROLES = {"textbox", "searchbox", "text input"}
_ASSIGN_PATTERNS = (
    r"(?:fill|set|change)\s+(.+?)\s+(?:with|to)\s+(.+)",
    r"(?:type|enter)\s+(.+?)\s+(?:into|in|as)\s+(.+)",
    r"(?:select|choose)\s+(.+?)\s+(?:in|from)\s+(.+?)(?:\s+dropdown|\s+combobox)?",
)


@dataclass(frozen=True)
class UserCommand:
    kind: CommandKind
    ref: str
    label: str
    value: str | None = None
    checked: bool | None = None

    @property
    def evidence(self) -> str:
        if self.kind == "type":
            return f"field_matches_task:{self.ref}"
        if self.kind == "select":
            return f"selection_matches_task:{self.ref}"
        if self.kind == "check":
            return f"checked_matches_task:{self.ref}"
        return f"verified_action:click:{self.ref}"


def user_commands(
    task: str, observation: AgentObservation, *, require_complete: bool = False
) -> tuple[UserCommand, ...] | None:
    """Only user text and supplied semantic controls establish command intent.

    Unknown clauses invalidate a complete microtask. In a larger task, known
    field assignments can supply bounded values while planning handles the
    remaining clauses. Duplicate or conflicting assignments fail closed.
    """
    if not task or len(task) > 8000:
        return None
    commands: list[UserCommand] = []
    for clause in command_clauses(task):
        if re.match(r"^(?:finish|stop)\b", clause, re.I):
            if require_complete and not re.search(r'"[^"\r\n]+"', clause):
                return None
            continue
        command = _bind_clause(clause, observation)
        if command is None:
            referenced = _assignment_label(clause)
            if referenced and any(
                _normal(previous.label) == _normal(referenced) for previous in commands
            ):
                return None
            if require_complete:
                return None
            continue
        if any(previous.ref == command.ref for previous in commands):
            return None
        commands.append(command)
        if len(commands) > 8:
            return None
    return tuple(commands) if commands else None


def command_clauses(task: str) -> tuple[str, ...]:
    """Split imperative clauses outside quoted values, including email dots."""
    clauses: list[str] = []
    start = 0
    quote: str | None = None
    index = 0
    while index < len(task):
        char = task[index]
        if quote is not None:
            if char == quote:
                quote = None
        elif char in {'"', "'"} and (index == 0 or not task[index - 1].isalnum()):
            quote = char
        elif char in {";", "\n"} or (
            char == "." and (index + 1 == len(task) or task[index + 1].isspace())
        ):
            clauses.append(task[start:index].strip())
            start = index + 1
        else:
            match = _SEPARATOR.match(task, index)
            if match:
                clauses.append(task[start:index].strip())
                start = match.end()
                index = match.end() - 1
        index += 1
    if quote is not None:
        return ()
    clauses.append(task[start:].strip())
    return tuple(clause.removeprefix("Please ").strip() for clause in clauses if clause)


def _normal(value: str) -> str:
    words = re.findall(r"[\w]+", value.casefold())
    return " ".join(word for word in words if word not in {"a", "an", "the"})


def _literal(value: str) -> str:
    value = value.strip().rstrip(".").strip()
    if len(value) > 1 and value[0] in {'"', "'"} and value[-1] == value[0]:
        return value[1:-1]
    return value


def _unique(label: str, observation: AgentObservation, roles: set[str]) -> PrunedElement | None:
    eligible = [
        element
        for element in observation.elements
        if (element.interactable or "disabled" in element.state)
        and element.role.casefold() in roles
    ]
    exact = [
        element
        for element in eligible
        if " ".join((element.name or "").split()).casefold() == " ".join(label.split()).casefold()
    ]
    matches = exact or [
        element for element in eligible if _normal(element.name or "") == _normal(label)
    ]
    if not matches and len(_normal(label).split()) >= 2:
        matches = [
            element
            for element in eligible
            if _normal(element.name or "").endswith(" " + _normal(label))
        ]
    return matches[0] if len(matches) == 1 else None


def _bind_clause(clause: str, observation: AgentObservation) -> UserCommand | None:
    # End-user natural phrasing is accepted only when the target is unique and
    # the value is literal task text. Page contents never provide input values.
    for index, pattern in enumerate(_ASSIGN_PATTERNS):
        match = re.fullmatch(pattern, clause, re.I)
        if match is None:
            continue
        first, second = map(_literal, match.groups())
        label, value = (first, second) if index == 0 else (second, first)
        element = _unique(label, observation, _TEXT_ROLES | {"combobox"})
        if element is None or not value or len(value) > 256:
            return None
        if element.role.casefold() == "combobox":
            options = [
                option.name or option.text or ""
                for option in observation.elements
                if option.role.casefold() == "option"
                and (option.parent_ref is None or option.parent_ref == element.ref)
                and _normal(option.name or option.text or "") == _normal(value)
            ]
            if len(options) != 1:
                return None
            return UserCommand("select", element.ref, element.name or label, options[0])
        if index == 2:
            return None
        return UserCommand("type", element.ref, element.name or label, value)

    checks = (
        (r"(?:check|enable|turn\s+on)\s+(.+)", True),
        (r"(?:uncheck|disable|turn\s+off)\s+(.+)", False),
        (r"(?:turn|switch)\s+(.+?)\s+on", True),
        (r"(?:turn|switch)\s+(.+?)\s+off", False),
    )
    for pattern, desired in checks:
        match = re.fullmatch(pattern, clause, re.I)
        if match:
            label = _literal(match.group(1))
            element = _unique(label, observation, {"checkbox", "switch", "radio"})
            if element is None:
                return None
            return UserCommand("check", element.ref, element.name or label, checked=desired)

    match = re.fullmatch(r"(?:click|tap|press)\s+(.+?)(?:\s+exactly\s+once)?", clause, re.I)
    if match:
        label = _literal(match.group(1))
        element = _unique(label, observation, {"button", "link"})
        if element is not None:
            return UserCommand("click", element.ref, element.name or label)
        return None

    verb = re.match(
        r"^(archive|restore|open|continue|save|submit|send|delete|publish|pin|apply|refresh|confirm|increment)\b",
        clause,
        re.I,
    )
    if verb:
        element = _unique(clause, observation, {"button", "link"})
        if element is None and re.search(r"\b(?:to|for)\b", clause, re.I):
            element = _unique(verb.group(1), observation, {"button", "link"})
        if element is not None:
            return UserCommand("click", element.ref, element.name or clause)
    return None


def _assignment_label(clause: str) -> str | None:
    for index, pattern in enumerate(_ASSIGN_PATTERNS):
        match = re.fullmatch(pattern, clause, re.I)
        if match:
            return _literal(match.group(1 if index == 0 else 2))
    return None
