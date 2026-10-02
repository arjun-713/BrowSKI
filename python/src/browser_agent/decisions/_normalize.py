"""Shared provider-output normalization and provider-local confidence gating."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from browser_agent.decisions.base import DecisionAnswer, DecisionKind, DecisionQuestion
from browser_agent.decisions.calibration import CalibrationPolicy


def get_value(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def normalize_answer(
    kind: DecisionKind,
    answer: Any,
    question: DecisionQuestion,
    policy: CalibrationPolicy,
) -> DecisionAnswer:
    probabilities = get_value(answer, "probabilities", {}) or {}
    probabilities = {str(key): float(value) for key, value in probabilities.items()}
    calibrated: dict[str, float] = {}
    value: str | float | bool

    if kind == DecisionKind.CHOICE:
        value = str(get_value(answer, "choice"))
        has_distribution = bool(probabilities)
        confidence_raw = float(
            get_value(answer, "answer_confidence", max(probabilities.values(), default=0.0))
        )
        if has_distribution:
            calibrated = policy.calibrate_probabilities(kind, probabilities)
            confidence_calibrated = max(calibrated.values(), default=confidence_raw)
        else:
            confidence_raw = float(
                get_value(answer, "answer_confidence", get_value(answer, "confidence", 0.0))
            )
            confidence_calibrated = policy.calibrate_binary(kind, confidence_raw)
            calibrated = {value: confidence_calibrated}
    elif kind == DecisionKind.SCORE:
        value = float(get_value(answer, "score"))
        if probabilities and isinstance(question.criteria, tuple):
            probabilities = {
                str(index): probabilities.get(str(index), probabilities.get(label, 0.0))
                for index, label in enumerate(question.criteria)
            } or probabilities
        confidence_raw = float(
            get_value(answer, "confidence", max(probabilities.values(), default=0.0))
        )
        if probabilities:
            calibrated = policy.calibrate_probabilities(kind, probabilities)
            confidence_calibrated = max(calibrated.values(), default=confidence_raw)
        else:
            confidence_calibrated = policy.calibrate_binary(kind, confidence_raw)
    else:
        value = float(get_value(answer, "noul"))
        confidence_raw = float(get_value(answer, "confidence", max(value, 1 - value)))
        yes_probability = policy.calibrate_binary(kind, value)
        confidence_calibrated = max(yes_probability, 1 - yes_probability)
        calibrated = {"yes": yes_probability, "no": 1 - yes_probability}

    threshold = policy.threshold_for(kind)
    accepted = None if threshold is None else confidence_calibrated >= threshold
    return DecisionAnswer(
        kind=kind,
        value=value,
        probabilities=calibrated,
        confidence_raw=confidence_raw,
        confidence_calibrated=confidence_calibrated,
        accepted=accepted,
        raw=answer,
    )
