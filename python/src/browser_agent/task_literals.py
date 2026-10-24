"""Bounded field literals from user instructions, independent of either runtime."""

from __future__ import annotations

import re
import unicodedata

MAX_BINDINGS = 8
MAX_LABEL_CHARS = 120
MAX_VALUE_CHARS = 256


def normalize_field_label(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(normalized.split())


class TaskLiteralError(ValueError):
    """Explicit field instructions are ambiguous or outside the supported bounds."""


def quoted_transfer_labels(task: str, *, strict: bool = False) -> tuple[str, str] | None:
    """Parse one user-authorized source/destination pair, never a page instruction."""
    if len(task) > 8000:
        if strict:
            raise TaskLiteralError("Task exceeds the 8000-character intent bound.")
        return None
    outside = _instruction_positions(task, strict=strict)
    pattern = re.compile(
        r'\btransfer\s+(?P<sq>["\'])(?P<source>(?:(?!(?P=sq))[^\r\n]){1,120})(?P=sq)'
        r'\s+from\s+supporting\s+page\s+into\s+(?P<dq>["\'])'
        r"(?P<destination>(?:(?!(?P=dq))[^\r\n]){1,120})(?P=dq)",
        re.I,
    )
    matches = [m for m in pattern.finditer(task) if m.start() in outside]
    requested = {
        m.start("verb")
        for m in re.finditer(
            r"(?:^|[.;,\n]|\b(?:and|then)\b)\s*(?:please\s+)?(?P<verb>transfer)\s+",
            task,
            re.I,
        )
        if m.start("verb") in outside
    }
    labels = (
        (matches[0].group("source").strip(), matches[0].group("destination").strip())
        if len(matches) == 1
        else None
    )
    valid = labels is not None and all(
        label and not any(ord(c) < 0x20 or ord(c) == 0x7F for c in label) for label in labels
    )
    if len(matches) > 1 or requested - {m.start() for m in matches} or (matches and not valid):
        if strict:
            raise TaskLiteralError(
                'Use one transfer "Source label" from supporting page into "Field label".'
            )
        return None
    return labels if valid else None


def _instruction_positions(task: str, *, strict: bool) -> set[int]:
    outside: set[int] = set()
    quote: str | None = None
    for index, character in enumerate(task):
        if quote is None:
            outside.add(index)
            if character in {'"', "'"} and (index == 0 or not task[index - 1].isalnum()):
                quote = character
        elif character == quote:
            quote = None
    if strict and quote is not None:
        raise TaskLiteralError("Field instructions contain an unfinished quote.")
    return outside


def quoted_click_target(task: str) -> str | None:
    """One explicit named transition; literal contents cannot create actions."""
    if len(task) > 8000:
        raise TaskLiteralError("Task exceeds the 8000-character intent bound.")
    outside = _instruction_positions(task, strict=True)
    pattern = re.compile(
        r'\b(?:click|press)\s+(?:the\s+)?(?P<quote>["\'])'
        rf"(?P<label>(?:(?!(?P=quote))[^\r\n]){{1,{MAX_LABEL_CHARS}}}?)(?P=quote)",
        re.I,
    )
    matches = [match for match in pattern.finditer(task) if match.start() in outside]
    requested = {
        match.start()
        for match in re.finditer(r'\b(?:click|press)\s+(?:the\s+)?["\']', task, re.I)
        if match.start() in outside
    }
    if requested - {match.start() for match in matches}:
        raise TaskLiteralError("The named click label must be quoted and within bounds.")
    if any(re.match(r"\s+(?:twice|again|\d+\s+times)\b", task[m.end() :], re.I) for m in matches):
        raise TaskLiteralError("Fast currently supports one explicit named click per task.")
    targets = [match.group("label") for match in matches]
    if len(targets) > 1:
        raise TaskLiteralError("Fast currently supports one explicit named click per task.")
    if not targets:
        return None
    label = targets[0]
    if not label.strip() or any(ord(c) < 0x20 or ord(c) == 0x7F for c in label):
        raise TaskLiteralError("The named click target must be a bounded plain label.")
    return normalize_field_label(label)


def quoted_field_values(task: str, *, strict: bool = False) -> dict[str, str]:
    """Reuse the supported set/fill/type grammar; conflicts never yield a value.

    Only the caller's task may enter this function. Never pass page text here.
    Labels and values must both be quoted. Too many assignments fail closed.
    """
    if len(task) > 8000:
        if strict:
            raise TaskLiteralError("Task exceeds the 8000-character field-intent bound.")
        return {}
    outside = _instruction_positions(task, strict=strict)
    bindings: dict[str, str] = {}
    conflicts: set[str] = set()
    matched: set[int] = set()
    count = 0
    for pattern in _patterns():
        for match in pattern.finditer(task):
            if match.start() not in outside:
                continue
            label = normalize_field_label(match.group("field"))
            value = match.group("value")
            if (
                not label
                or not value.strip()
                or any(ord(character) < 0x20 or ord(character) == 0x7F for character in value)
            ):
                continue
            matched.add(match.start())
            count += 1
            if count > MAX_BINDINGS:
                if strict:
                    raise TaskLiteralError(
                        "At most eight explicit field assignments are supported."
                    )
                return {}
            if label in bindings and bindings[label] != value:
                conflicts.add(label)
            bindings[label] = value
    # Reject unsupported imperative field syntax instead of treating an empty
    # plan as proof that a form goal has no requirements. Literal contents are
    # excluded by the same quote scan as successful bindings.
    prefix = re.compile(
        r"(?:^|[.;,\n]|\b(?:and|then)\b)\s*(?:please\s+)?"
        r"(?P<verb>set|fill|type|enter|change)\s+",
        re.I,
    )
    requested = {
        match.start("verb") for match in prefix.finditer(task) if match.start("verb") in outside
    }
    if strict and (conflicts or requested - matched):
        raise TaskLiteralError(
            "Field labels/values must be quoted, within bounds and without conflicting assignments."
        )
    return {label: value for label, value in bindings.items() if label not in conflicts}


def _patterns() -> tuple[re.Pattern[str], ...]:
    # Exclude the active quote from each capture using a lookahead, while
    # allowing the other quote style inside a value such as "O'Reilly".
    field = (
        r'(?P<field_quote>["\'])(?P<field>'
        rf"(?:(?!(?P=field_quote))[^\r\n]){{1,{MAX_LABEL_CHARS}}}?)(?P=field_quote)"
    )
    value = (
        r'(?P<value_quote>["\'])(?P<value>'
        rf"(?:(?!(?P=value_quote))[^\r\n]){{1,{MAX_VALUE_CHARS}}}?)(?P=value_quote)"
    )
    return (
        re.compile(r"\bset\s+" + field + r"\s+to\s+" + value, re.IGNORECASE),
        re.compile(r"\bfill\s+" + field + r"\s+with\s+" + value, re.IGNORECASE),
        re.compile(r"\btype\s+" + value + r"\s+into\s+" + field, re.IGNORECASE),
    )
