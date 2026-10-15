"""Narrow policy exceptions for preserved browser state during planning."""

from __future__ import annotations

import re
from collections.abc import Mapping

from browser_agent._types import SemanticSnapshot, TaskState
from browser_agent.progress.evidence import in_viewport

_DRAFT_PRESERVATION_REQUEST = re.compile(
    r"\b(?:do\s+not|don't|never)\s+submit\b"
    r"|\b(?:leave|keep)\b[^\r\n.!?]{0,100}\b(?:as\s+(?:a\s+)?)?draft\b",
    re.I,
)
_NEGATED_SUBMISSION = re.compile(
    r"\b(?:no|not|never)\b[^\r\n.!?]{0,60}\b(?:submitted|sent)\b",
    re.I,
)
_UNSUBMITTED_STATE = re.compile(r"\b(?:unsubmitted|unsent)\b", re.I)


def requested_draft_state_has_pending_field_obligation(
    evidence: str,
    task: TaskState,
    browser_checks: Mapping[str, bool],
    snapshot: SemanticSnapshot,
) -> bool:
    """Allow an explicit preserved draft status beside unfinished user inputs.

    The evidence must exactly match a visible status line and fully describe a
    negative submission state. Other pending page prose or static headings do
    not qualify as current state.
    """
    if not evidence.startswith("visible_text:"):
        return False

    if not _DRAFT_PRESERVATION_REQUEST.search(task.user_goal or task.task):
        return False

    phrase = _normalize_line(evidence.removeprefix("visible_text:"))
    if not phrase or not _fully_describes_draft_state(phrase):
        return False

    status_lines = [
        _normalize_line(line)
        for element in snapshot.elements
        if element.role.casefold() == "status" and in_viewport(element, snapshot)
        for line in (element.text or element.accessible_name or "").splitlines()
    ]
    if phrase not in status_lines:
        return False

    if any(_has_positive_submission_claim(line) for line in status_lines):
        return False

    return _has_pending_authorized_control(browser_checks, snapshot)


def _fully_describes_draft_state(phrase: str) -> bool:
    submission_terms = re.findall(r"\b(?:submitted|sent)\b", phrase)
    if re.search(r"\bdraft\b", phrase):
        return (
            not submission_terms
            and not re.search(r"\b(?:no|not|never)\b", phrase)
            and re.fullmatch(
                r"(?:[a-z0-9 _-]{1,60}\s+(?:is|remains|stays)\s+(?:a\s+)?)?draft",
                phrase,
            )
            is not None
        )
    if _UNSUBMITTED_STATE.search(phrase):
        return (
            not submission_terms
            and not re.search(r"\b(?:no|not|never)\b", phrase)
            and re.fullmatch(r"(?:[a-z0-9 _-]{1,60}\s+)?(?:unsubmitted|unsent)", phrase) is not None
        )
    return bool(_NEGATED_SUBMISSION.search(phrase)) and len(submission_terms) == 1


def _has_positive_submission_claim(status_line: str) -> bool:
    if not re.search(r"\b(?:submitted|sent)\b", status_line):
        return False
    return _NEGATED_SUBMISSION.fullmatch(status_line) is None


def _has_pending_authorized_control(
    browser_checks: Mapping[str, bool], snapshot: SemanticSnapshot
) -> bool:
    eligible_roles = {
        "field_matches_task": {"textbox", "text input"},
        "selection_matches_task": {"combobox"},
        "checked_matches_task": {"checkbox", "radio", "switch"},
    }
    for key, satisfied in browser_checks.items():
        if satisfied:
            continue
        check_type, separator, ref = key.partition(":")
        if not separator or check_type not in eligible_roles:
            continue
        element = snapshot.by_ref(ref)
        if (
            element is not None
            and element.visible
            and element.role.casefold() in eligible_roles[check_type]
        ):
            return True
    return False


def _normalize_line(value: str) -> str:
    return " ".join(value.casefold().split()).rstrip(".!?")
