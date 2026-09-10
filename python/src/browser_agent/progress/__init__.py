"""Progress tracking: task state, completion criteria, stagnation detection."""

from browser_agent.progress.task_state import (
    StagnationDetector,
    check_completion,
)

__all__ = ["StagnationDetector", "check_completion"]
