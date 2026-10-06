"""Provider-specific calibration and acceptance thresholds."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from math import exp, log

from browser_agent.decisions.base import DecisionKind


@dataclass(frozen=True)
class CalibrationPolicy:
    """Temperature and minimum confidence fitted for one provider and task set."""

    temperatures: Mapping[DecisionKind, float] = field(
        default_factory=lambda: dict[DecisionKind, float]()
    )
    minimum_confidence: Mapping[DecisionKind, float] = field(
        default_factory=lambda: dict[DecisionKind, float]()
    )
    calibration_id: str | None = None

    def __post_init__(self) -> None:
        if any(value <= 0 for value in self.temperatures.values()):
            raise ValueError("calibration temperatures must be greater than zero")
        if any(not 0 <= value <= 1 for value in self.minimum_confidence.values()):
            raise ValueError("minimum confidence thresholds must be between zero and one")

    def calibrate_probabilities(
        self, kind: DecisionKind, values: Mapping[str, float]
    ) -> dict[str, float]:
        temperature = self.temperatures.get(kind, 1.0)
        if not values:
            return {}
        logits = {key: log(max(value, 1e-12)) / temperature for key, value in values.items()}
        peak = max(logits.values())
        weights = {key: exp(value - peak) for key, value in logits.items()}
        total = sum(weights.values())
        return {key: value / total for key, value in weights.items()}

    def calibrate_binary(self, kind: DecisionKind, value: float) -> float:
        probability = min(max(value, 1e-12), 1 - 1e-12)
        temperature = self.temperatures.get(kind, 1.0)
        logit = log(probability / (1 - probability)) / temperature
        return 1 / (1 + exp(-logit))

    def threshold_for(self, kind: DecisionKind) -> float | None:
        return self.minimum_confidence.get(kind)


def _laya_evaluation_policy() -> CalibrationPolicy:
    """Record the evaluated checkpoint while keeping execution fail-closed."""
    return CalibrationPolicy(calibration_id="laya-v1-v2-2026-10-06-no-execution-threshold")


@dataclass(frozen=True)
class ProviderCalibration:
    """Independent policy table; Laya and Jev must be calibrated separately."""

    laya: CalibrationPolicy = field(default_factory=_laya_evaluation_policy)
    jev: CalibrationPolicy = field(default_factory=CalibrationPolicy)

    def for_provider(self, provider: str) -> CalibrationPolicy:
        if provider == "laya":
            return self.laya
        if provider == "jev":
            return self.jev
        raise ValueError(f"unknown decision provider: {provider}")
