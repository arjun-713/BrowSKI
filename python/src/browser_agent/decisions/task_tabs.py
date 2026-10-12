"""Finite tab choices from explicit task URLs and Rust-owned tab identities."""

from __future__ import annotations

import re
from collections.abc import Iterable
from urllib.parse import urlsplit, urlunsplit

from browser_agent._types import SemanticSnapshot
from browser_agent.decisions.candidates import ActionCandidate, CandidateKind

_OPEN_TAB = re.compile(
    r"\bopen\s+(?P<quote>[\"']?)(?P<url>https?://[^\s\"'<>]{1,2048})"
    r"(?P=quote)\s+in\s+(?:a\s+)?new\s+tab\b",
    re.IGNORECASE,
)
_OPEN_EXACT_PAGES = re.compile(
    r"\bopen\s+(?:the\s+)?exact\s+pages?\s+(?P<targets>.*?)"
    r"\bin\s+(?:(?:separate\s+)?(?:browser\s+)?tabs?|(?:a\s+)?new\s+tab)\b",
    re.IGNORECASE | re.DOTALL,
)
_URL_IN_CLAUSE = re.compile(
    r"(?P<quote>[\"']?)(?P<url>https?://[^\s\"'<>]{1,2048})(?P=quote)",
    re.IGNORECASE,
)
_SET_FILL_INPUT = re.compile(
    r"\b(?:set|fill)\s+(?P<field_quote>[\"'])"
    r"(?:(?!(?P=field_quote))[^\r\n]){1,120}(?P=field_quote)\s+"
    r"(?:to|with)\s+(?P<value_quote>[\"'])"
    r"(?:(?!(?P=value_quote))[^\r\n]){1,2048}(?P=value_quote)",
    re.IGNORECASE,
)
_TYPE_INPUT = re.compile(
    r"\btype\s+(?P<value_quote>[\"'])"
    r"(?:(?!(?P=value_quote))[^\r\n]){1,2048}(?P=value_quote)\s+into\s+"
    r"(?P<field_quote>[\"'])"
    r"(?:(?!(?P=field_quote))[^\r\n]){1,120}(?P=field_quote)",
    re.IGNORECASE,
)
_MAX_OWNED_TABS = 8
_MAX_REQUESTED_URLS = 8


def with_owned_tab_candidates(
    candidates: list[ActionCandidate],
    *,
    task: str,
    snapshot: SemanticSnapshot,
    max_candidates: int,
    owned_tab_urls: Iterable[str] = (),
) -> list[ActionCandidate]:
    """Never accept a model-generated destination or an unowned tab reference.

    Destinations must be explicit HTTP(S) URLs in the user's task. Callers may
    provide URLs from the current Rust-owned tab inventory to suppress opening
    duplicates; snapshot tab IDs alone do not carry their destinations.
    Activation is restricted to the current Rust session registry, and the
    extension enforces ownership again. Closing tabs remains a separately
    controlled runtime operation.
    """
    additions: list[ActionCandidate] = []
    urls: set[str] = set()
    existing_urls = {
        normalized
        for url in (snapshot.url, *owned_tab_urls)
        if (normalized := _normalized_http_url(url)) is not None
    }
    available_slots = max(0, _MAX_OWNED_TABS - len(snapshot.tabs))
    url_limit = min(_MAX_REQUESTED_URLS, available_slots)
    if url_limit:
        for url in explicit_task_destinations(task):
            normalized = _normalized_http_url(url)
            if normalized is None:
                continue
            if normalized in urls or normalized in existing_urls:
                continue
            urls.add(normalized)
            additions.append(
                ActionCandidate(
                    candidate_id="",
                    kind=CandidateKind.BROWSER_ACTION,
                    description=f"Open the user-specified URL {url} in a new owned tab.",
                    action_type="new_tab",
                    url=url,
                    observed_generation=snapshot.state_generation,
                )
            )
            if len(additions) >= url_limit:
                break

    for tab in snapshot.tabs[:8]:
        if tab == snapshot.active_tab:
            continue
        additions.append(
            ActionCandidate(
                candidate_id="",
                kind=CandidateKind.BROWSER_ACTION,
                description=f"Activate the already owned browser tab {tab}.",
                action_type="activate_tab",
                tab=tab,
                observed_generation=snapshot.state_generation,
            )
        )

    escalation = [
        candidate for candidate in candidates if candidate.kind == CandidateKind.ESCALATE_TO_PLANNER
    ][:1]
    normal = [
        candidate for candidate in candidates if candidate.kind == CandidateKind.BROWSER_ACTION
    ]
    # Reserve room for owned-tab choices and escalation without exceeding the
    # existing finite candidate cap. No unbounded list is sent to a provider.
    additions = additions[: max_candidates - len(escalation) - 1]
    normal = normal[: max_candidates - len(additions) - len(escalation)]
    return [
        candidate.model_copy(update={"candidate_id": f"c{index:02d}"})
        for index, candidate in enumerate(normal + additions + escalation, start=1)
    ]


def explicit_task_destinations(task: str) -> list[str]:
    """Return bounded HTTP(S) URLs from explicit user open clauses only.

    Recognizes individual ``open URL in a new tab`` instructions and explicit
    ``open the exact pages URL1, URL2 in separate browser tabs`` lists. URL
    mentions in ordinary task text or form values do not authorize navigation.
    """
    if len(task) > 8_000:
        return []

    requested: list[str] = []
    seen: set[str] = set()
    matches: list[tuple[int, str]] = []
    searchable_task = _mask_typed_values(task)

    for match in _OPEN_TAB.finditer(searchable_task):
        matches.append((match.start(), match.group("url")))

    for clause in _OPEN_EXACT_PAGES.finditer(searchable_task):
        for match in _URL_IN_CLAUSE.finditer(clause.group("targets")):
            matches.append((clause.start("targets") + match.start(), match.group("url")))

    for _, url in sorted(matches, key=lambda item: item[0]):
        _append_valid_url(requested, seen, url)
        if len(requested) == _MAX_REQUESTED_URLS:
            break

    return requested


def _append_valid_url(requested: list[str], seen: set[str], candidate: str) -> None:
    url = candidate.rstrip(".,;!?)")
    normalized = _normalized_http_url(url)
    if normalized is None or normalized in seen:
        return
    seen.add(normalized)
    requested.append(url)


def _mask_typed_values(task: str) -> str:
    spans = [
        match.span()
        for pattern in (_SET_FILL_INPUT, _TYPE_INPUT)
        for match in pattern.finditer(task)
    ]
    if not spans:
        return task

    characters = list(task)
    for start, end in spans:
        for index in range(start, end):
            if characters[index] not in "\r\n":
                characters[index] = " "
    return "".join(characters)


def _normalized_http_url(url: str) -> str | None:
    if (
        not url
        or len(url) > 2_048
        or any(character.isspace() for character in url)
        or any(ord(character) < 32 for character in url)
    ):
        return None
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        return None

    scheme = parsed.scheme.casefold()
    hostname = parsed.hostname
    if (
        scheme not in {"http", "https"}
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or port == 0
    ):
        return None

    normalized_host = hostname.casefold()
    if ":" in normalized_host:
        normalized_host = f"[{normalized_host}]"
    if port is not None and port != (80 if scheme == "http" else 443):
        normalized_host = f"{normalized_host}:{port}"

    return urlunsplit((scheme, normalized_host, parsed.path or "/", parsed.query, parsed.fragment))
