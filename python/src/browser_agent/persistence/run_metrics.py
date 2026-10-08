"""Typed, content-free aggregates for local run observability."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from browser_agent.agent.events import RuntimeEvent

_MAX_COUNT = 2**31 - 1


class RunMetricKind(StrEnum):
    """Safe counters that can be incremented by trusted runtime code."""

    VISION_CALL = "vision_call"
    LUNA_NONE_EFFORT_CALL = "luna_none_effort_call"
    LUNA_LOW_EFFORT_CALL = "luna_low_effort_call"
    LUNA_HIGH_EFFORT_CALL = "luna_high_effort_call"
    LAYA_SHADOW_DECISION = "laya_shadow_decision"


@dataclass(frozen=True, slots=True)
class RunMetrics:
    """Bounded aggregate counters; deliberately contains no labels or values."""

    task_duration_ms: int = 0
    action_count: int = 0
    verification_failures: int = 0
    recoveries: int = 0
    browser_code_calls: int = 0
    vision_calls: int = 0
    luna_calls: int = 0
    luna_none_effort_calls: int = 0
    luna_low_effort_calls: int = 0
    luna_high_effort_calls: int = 0
    laya_shadow_decisions: int = 0

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            value = getattr(self, name)
            if type(value) is not int or not 0 <= value <= _MAX_COUNT:
                raise ValueError("run metrics must be bounded non-negative integers")

    def to_dict(self) -> dict[str, int]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    @classmethod
    def from_dict(cls, values: object) -> RunMetrics:
        if not isinstance(values, dict):
            return cls()
        typed_values = cast(dict[object, object], values)
        allowed = cls.__dataclass_fields__
        cleaned = {
            name: value
            for name, value in typed_values.items()
            if isinstance(name, str)
            and name in allowed
            and type(value) is int
            and 0 <= value <= _MAX_COUNT
        }
        return cls(**cleaned)


class RunMetricsAggregator:
    """In-memory accumulation restored from local aggregate metadata on resume."""

    def __init__(self) -> None:
        self._runs: dict[str, RunMetrics] = {}

    def ensure(self, run_id: str) -> None:
        self._runs.setdefault(run_id, RunMetrics())

    def restore(self, run_id: str, metrics: RunMetrics) -> None:
        self._runs[run_id] = metrics

    def increment(self, run_id: str, kind: RunMetricKind) -> None:
        metrics = self._runs.get(run_id, RunMetrics())
        field = {
            RunMetricKind.VISION_CALL: "vision_calls",
            RunMetricKind.LUNA_NONE_EFFORT_CALL: "luna_none_effort_calls",
            RunMetricKind.LUNA_LOW_EFFORT_CALL: "luna_low_effort_calls",
            RunMetricKind.LUNA_HIGH_EFFORT_CALL: "luna_high_effort_calls",
            RunMetricKind.LAYA_SHADOW_DECISION: "laya_shadow_decisions",
        }[kind]
        updated = _increment(metrics, field)
        if kind in {
            RunMetricKind.LUNA_LOW_EFFORT_CALL,
            RunMetricKind.LUNA_NONE_EFFORT_CALL,
            RunMetricKind.LUNA_HIGH_EFFORT_CALL,
        }:
            updated = _increment(updated, "luna_calls")
        self._runs[run_id] = updated

    def observe_event(self, event: RuntimeEvent) -> RunMetrics:
        metrics = self._runs.get(event.run_id, RunMetrics())
        event_type = event.type.value
        if event_type == "ActionCompleted":
            metrics = _increment(metrics, "action_count")
        elif event_type == "VerificationCompleted" and event.status == "failed":
            metrics = _increment(metrics, "verification_failures")
        elif event_type == "RecoveryStarted":
            metrics = _increment(metrics, "recoveries")
        elif event_type == "BrowserCodeStarted":
            metrics = _increment(metrics, "browser_code_calls")
        self._runs[event.run_id] = metrics
        return metrics

    def set_duration(self, run_id: str, duration_ms: int) -> RunMetrics:
        if type(duration_ms) is not int or not 0 <= duration_ms <= _MAX_COUNT:
            raise ValueError("run duration must be a bounded non-negative integer")
        current = self._runs.get(run_id, RunMetrics())
        updated = replace(current, task_duration_ms=duration_ms)
        self._runs[run_id] = updated
        return updated

    def get(self, run_id: str) -> RunMetrics:
        return self._runs.get(run_id, RunMetrics())


def _increment(metrics: RunMetrics, field: str) -> RunMetrics:
    return replace(metrics, **{field: min(_MAX_COUNT, getattr(metrics, field) + 1)})
