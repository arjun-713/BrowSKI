"""Explicit run budgets, kept separate from immutable task gold labels."""

from dataclasses import asdict, dataclass

from benchmarks.task_mix.schema import TaskCase


@dataclass(frozen=True)
class ExecutionPolicy:
    budget_scale: int = 1
    difficulty: str = "all"
    max_steps: int = 120
    max_luna_calls: int = 30
    max_case_seconds: int | None = None

    def __post_init__(self) -> None:
        if self.budget_scale not in (1, 2, 3):
            raise ValueError("budget scale must be 1, 2, or 3")
        if self.difficulty not in {"all", "small", "medium", "large"}:
            raise ValueError("unknown task difficulty")
        if not 1 <= self.max_steps <= 120 or not 1 <= self.max_luna_calls <= 60:
            raise ValueError("run bounds require 1–120 steps and 1–60 Luna calls")
        if self.max_case_seconds is not None and not 1 <= self.max_case_seconds <= 180:
            raise ValueError("case timeout must be in 1–180 seconds")

    @property
    def seconds_cap(self) -> int:
        return self.max_case_seconds or min(180, 120 * self.budget_scale)

    def describe(self) -> dict[str, object]:
        return asdict(self)

    def case_limits(self, case: TaskCase) -> tuple[int, int, float]:
        steps = min(case.max_steps * self.budget_scale, self.max_steps)
        calls = min(case.max_reasoning_calls * self.budget_scale, self.max_luna_calls)
        seconds = min(self.seconds_cap, case.max_seconds * self.budget_scale)
        return steps, calls, float(seconds)
