"""Rank existing semantic action candidates by task and subgoal relevance."""

from __future__ import annotations

import re

from browser_agent._types import AgentObservation, PrunedElement
from browser_agent.decisions.task_search import (
    extract_task_search_query,
    task_search_values_by_ref,
)

_WORD = re.compile(r"[\w]+", re.UNICODE)
_LOW_SIGNAL_WORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "at",
        "buy",
        "can",
        "click",
        "do",
        "find",
        "for",
        "from",
        "in",
        "into",
        "me",
        "my",
        "new",
        "of",
        "on",
        "open",
        "please",
        "search",
        "select",
        "set",
        "tab",
        "the",
        "then",
        "to",
        "with",
    }
)


def rank_observation_for_candidates(
    observation: AgentObservation,
    *,
    task: str,
    current_subgoal: str,
) -> AgentObservation:
    """Prioritize relevant observed elements before candidate truncation.

    The returned observation contains the same elements with unchanged refs and
    data, reordered stably by task/subgoal relevance. This lets finite candidate
    construction retain relevant controls even below long navigation lists.
    """
    task_terms = _content_terms(task)
    subgoal_terms = _content_terms(current_subgoal)
    search_query = extract_task_search_query(current_subgoal)
    if search_query is not None:
        subgoal_terms.add("search")
    search_refs = set(task_search_values_by_ref(task, observation))

    scored: list[tuple[int, int, PrunedElement]] = []
    for index, element in enumerate(observation.elements):
        label_text = " ".join(part for part in (element.name, element.text) if part)
        label_terms = _content_terms(label_text)
        score = 3 * len(label_terms & subgoal_terms) + len(label_terms & task_terms)
        if search_query is not None and element.ref in search_refs:
            score += 16
        scored.append((score, index, element))

    scored.sort(key=lambda item: (-item[0], item[1]))
    return observation.model_copy(update={"elements": [element for _, _, element in scored]})


def _content_terms(text: str) -> set[str]:
    return {term for term in _WORD.findall(text.casefold()) if term not in _LOW_SIGNAL_WORDS}
