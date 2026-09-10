"""Working memory implementation notes (Milestone 5).

Rules enforced by :class:`WorkingMemory` (see ``_types.py``):
- raw historical context must not grow without bound (bounded deque);
- store compressed history, acquired facts, completed milestones, failed
  strategies — never raw full snapshots indefinitely.
"""

from browser_agent._types import WorkingMemory

__all__ = ["WorkingMemory"]
