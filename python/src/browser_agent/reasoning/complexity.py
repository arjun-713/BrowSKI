"""Deterministic gate for normal versus temporary high reasoning effort."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from browser_agent.reasoning.contracts import ReasoningEffort


class ComplexityLevel(StrEnum):
    NORMAL = "normal"
    VERY_COMPLEX = "very_complex"


class ComplexityReason(StrEnum):
    REPEATED_RECOVERY = "repeated_recovery"
    REPEATED_REPLAN = "repeated_replan"
    UNCERTAIN_VERIFICATION = "repeated_uncertain_verification"
    REPEATED_STATE = "repeated_state_fingerprint"
    NESTED_SUBGOALS = "nested_subgoals"
    DEPENDENCY_DEPTH = "task_dependency_depth"
    SEMANTIC_AMBIGUITY = "repeated_semantic_ambiguity"
    PLAN_STATE_MISMATCH = "repeated_plan_state_mismatch"
    CROSS_TAB_SYNTHESIS = "cross_tab_synthesis"
    CONFLICTING_CONSTRAINTS = "conflicting_constraints"
    VISION_REQUIRED = "vision_required"
    NORMAL_REPLAN_FAILED = "normal_replan_failed"


@dataclass(frozen=True)
class ComplexitySignals:
    """Measured task/runtime facts used by the deterministic complexity gate."""

    recovery_count: int = 0
    replan_count: int = 0
    uncertain_verification_count: int = 0
    repeated_state_fingerprint_count: int = 0
    active_subgoal_count: int = 1
    task_dependency_depth: int = 0
    semantic_ambiguity_count: int = 0
    plan_state_mismatch_count: int = 0
    tab_count: int = 1
    cross_tab_synthesis_required: bool = False
    conflicting_constraints: bool = False
    vision_required: bool = False
    normal_replan_failed: bool = False

    def __post_init__(self) -> None:
        counts = (
            self.recovery_count,
            self.replan_count,
            self.uncertain_verification_count,
            self.repeated_state_fingerprint_count,
            self.active_subgoal_count,
            self.task_dependency_depth,
            self.semantic_ambiguity_count,
            self.plan_state_mismatch_count,
            self.tab_count,
        )
        if any(count < 0 for count in counts):
            raise ValueError("complexity signal counts cannot be negative")


@dataclass(frozen=True)
class ComplexityResult:
    level: ComplexityLevel
    reasons: tuple[ComplexityReason, ...] = ()

    @property
    def effort(self) -> ReasoningEffort:
        """Return the only reasoning effort selected by this baseline gate."""
        return (
            ReasoningEffort.HIGH
            if self.level == ComplexityLevel.VERY_COMPLEX
            else ReasoningEffort.LOW
        )


@dataclass(frozen=True)
class ComplexityThresholds:
    repeated_recoveries: int = 3
    repeated_replans: int = 2
    uncertain_verifications: int = 2
    repeated_fingerprints: int = 2
    active_subgoals: int = 4
    dependency_depth: int = 3
    semantic_ambiguities: int = 2
    plan_state_mismatches: int = 2


class ComplexityGate:
    """Raise effort only for repeated or structurally complex task conditions."""

    def __init__(self, thresholds: ComplexityThresholds | None = None) -> None:
        self.thresholds = thresholds or ComplexityThresholds()

    def evaluate(self, signals: ComplexitySignals) -> ComplexityResult:
        limits = self.thresholds
        reasons: list[ComplexityReason] = []

        if signals.recovery_count >= limits.repeated_recoveries:
            reasons.append(ComplexityReason.REPEATED_RECOVERY)
        if signals.replan_count >= limits.repeated_replans:
            reasons.append(ComplexityReason.REPEATED_REPLAN)
        if signals.uncertain_verification_count >= limits.uncertain_verifications:
            reasons.append(ComplexityReason.UNCERTAIN_VERIFICATION)
        if signals.repeated_state_fingerprint_count >= limits.repeated_fingerprints:
            reasons.append(ComplexityReason.REPEATED_STATE)
        if signals.active_subgoal_count >= limits.active_subgoals:
            reasons.append(ComplexityReason.NESTED_SUBGOALS)
        if signals.task_dependency_depth >= limits.dependency_depth:
            reasons.append(ComplexityReason.DEPENDENCY_DEPTH)
        if signals.semantic_ambiguity_count >= limits.semantic_ambiguities:
            reasons.append(ComplexityReason.SEMANTIC_AMBIGUITY)
        if signals.plan_state_mismatch_count >= limits.plan_state_mismatches:
            reasons.append(ComplexityReason.PLAN_STATE_MISMATCH)
        if signals.tab_count > 1 and signals.cross_tab_synthesis_required:
            reasons.append(ComplexityReason.CROSS_TAB_SYNTHESIS)
        if signals.conflicting_constraints:
            reasons.append(ComplexityReason.CONFLICTING_CONSTRAINTS)
        if signals.vision_required:
            reasons.append(ComplexityReason.VISION_REQUIRED)
        if signals.normal_replan_failed:
            reasons.append(ComplexityReason.NORMAL_REPLAN_FAILED)

        level = ComplexityLevel.VERY_COMPLEX if reasons else ComplexityLevel.NORMAL
        return ComplexityResult(level=level, reasons=tuple(reasons))
