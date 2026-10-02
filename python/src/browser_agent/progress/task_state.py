"""Task state, progress detection, completion criteria, stagnation detection."""

from __future__ import annotations

from collections import deque

from browser_agent._types import SemanticSnapshot


def check_completion(goal: str, snapshot: SemanticSnapshot) -> bool:  # pragma: no cover
    """Completion-criteria hook for M7; deterministic rules are not wired yet."""
    _ = (goal, snapshot)
    return False


class StagnationDetector:
    """Detect repeated actions / unchanged state over a bounded window.

    The agent must detect stagnation and repeated actions (principle 9).
    History is bounded: only the last ``window`` fingerprints are kept.
    """

    def __init__(self, window: int = 5) -> None:
        self.window = window
        self._recent: deque[str] = deque(maxlen=window)

    def observe(self, page_fingerprint: str) -> None:
        self._recent.append(page_fingerprint)

    @property
    def is_stagnant(self) -> bool:
        return len(self._recent) == self.window and len(set(self._recent)) == 1

    def reset(self) -> None:
        self._recent.clear()
