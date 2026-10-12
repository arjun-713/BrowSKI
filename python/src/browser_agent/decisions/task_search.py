"""Extract bounded user search intent and bind it to observed search fields."""

from __future__ import annotations

import re
from collections.abc import Collection

from browser_agent._types import AgentObservation

_SEARCH_INTENT = re.compile(
    r"\b(?:search\s+for|find|buy)\s+(?:me\s+)?(?P<query>[^.!?\r\n]{1,512}?)"
    r"(?=\s+\b(?:and|then|can\s+you|on|from)\b|[,;.!?\r\n]|$)",
    re.IGNORECASE,
)
_CREDENTIAL_TERMS = frozenset(
    {
        "account",
        "auth",
        "authentication",
        "card",
        "code",
        "credential",
        "email",
        "login",
        "otp",
        "passcode",
        "password",
        "secret",
        "security",
        "token",
        "user",
        "username",
    }
)
_MAX_SEARCH_QUERY_CHARS = 256
_MAX_SEARCH_WORDS = 32


def extract_task_search_query(task: str) -> str | None:
    """Return an explicit search topic from a short natural task phrase.

    The topic comes only from the user's task. Page text and observed values
    never seed a search query.
    """
    if len(task) > 8_000:
        return None
    matches = list(_SEARCH_INTENT.finditer(task))
    if len(matches) != 1:
        return None

    query = " ".join(matches[0].group("query").strip().strip("\"'").split())
    if not query or len(query) > _MAX_SEARCH_QUERY_CHARS or len(query.split()) > _MAX_SEARCH_WORDS:
        return None
    return query


def task_search_values_by_ref(
    task: str,
    observation: AgentObservation,
    *,
    excluded_refs: Collection[str] = (),
) -> dict[str, str]:
    """Bind the task's search topic to one unique observed search control."""
    query = extract_task_search_query(task)
    if query is None:
        return {}

    matches = [
        element
        for element in observation.elements
        if element.interactable
        and element.ref not in excluded_refs
        and _is_search_control(element.role, element.name)
    ]
    if len(matches) != 1:
        return {}
    return {matches[0].ref: query}


def _is_search_control(role: str, name: str | None) -> bool:
    if not name:
        return False
    normalized_name = " ".join(name.casefold().replace("_", " ").split())
    terms = set(re.findall(r"[a-z0-9]+", normalized_name))
    if terms & _CREDENTIAL_TERMS:
        return False

    normalized_role = role.casefold()
    if normalized_role == "searchbox":
        return True
    if normalized_role not in {"textbox", "text input"}:
        return False

    return (
        any(term.startswith("search") for term in terms)
        or "keyword" in terms
        or "keywords" in terms
    )
