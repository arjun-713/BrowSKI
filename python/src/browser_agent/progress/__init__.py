"""Progress tracking: task state, completion criteria, stagnation detection."""

from browser_agent.progress.task_state import (
    ProgressReport,
    ProgressSignal,
    ProgressTracker,
    StagnationDetector,
    StagnationSample,
    check_completion,
)

__all__ = [
    "ProgressReport",
    "ProgressSignal",
    "ProgressTracker",
    "StagnationDetector",
    "StagnationSample",
    "check_completion",
]
