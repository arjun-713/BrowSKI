"""Finite tab choices from explicit task URLs and Rust-owned tab identities."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from browser_agent._types import SemanticSnapshot
from browser_agent.decisions.candidates import ActionCandidate, CandidateKind

_OPEN_TAB = re.compile(r'\bopen\s+"([^"\r\n]{1,2048})"\s+in\s+(?:a\s+)?new\s+tab\b', re.I)


def with_owned_tab_candidates(
    candidates: list[ActionCandidate],
    *,
    task: str,
    snapshot: SemanticSnapshot,
    max_candidates: int,
) -> list[ActionCandidate]:
    """Never accept a model-generated destination or an unowned tab reference.

    URLs must be explicitly quoted in the user's task. Activation is restricted
    to the current Rust session registry; the extension enforces ownership again.
    Closing tabs remains a separately controlled runtime operation.
    """
    additions: list[ActionCandidate] = []
    urls: set[str] = set()
    if len(task) <= 8_000 and len(snapshot.tabs) < 8:
        for match in _OPEN_TAB.finditer(task):
            url = match.group(1)
            try:
                parsed = urlsplit(url)
                port = parsed.port
            except ValueError:
                continue
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or any(character.isspace() for character in url)
                or any(ord(character) < 32 for character in url)
                or port == 0
                or url in urls
                or url == snapshot.url
            ):
                continue
            urls.add(url)
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
            if len(urls) == 2:
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
