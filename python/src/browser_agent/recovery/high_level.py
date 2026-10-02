"""Bounded recovery ladder above Rust's deterministic mechanical retries."""

from __future__ import annotations

from dataclasses import dataclass

from browser_agent._types import FailureKind, RecoveryDecision, RecoveryStep


@dataclass
class RecoveryBudget:
    mechanical_repairs: int = 0
    reobservations: int = 0
    alternate_actions: int = 0
    system_one_classifications: int = 0
    normal_replans: int = 0
    complexity_checks: int = 0
    high_replans: int = 0
    user_prompts: int = 0
    max_mechanical_repairs: int = 1
    max_reobservations: int = 1
    max_alternate_actions: int = 1
    max_system_one_classifications: int = 1
    max_normal_replans: int = 2
    max_complexity_checks: int = 1
    max_high_replans: int = 1
    max_user_prompts: int = 1


@dataclass(frozen=True)
class RecoveryContext:
    failure_kind: FailureKind
    mechanical_repair_available: bool = False
    alternate_action_available: bool = False
    system_one_available: bool = False
    reasoning_available: bool = False
    very_complex: bool = False
    user_intervention_allowed: bool = True


@dataclass
class RecoveryPolicy:
    """Choose the next bounded rung and persist the associated budget."""

    max_replans: int = 2

    def next_step(
        self,
        context: RecoveryContext,
        budget: RecoveryBudget,
    ) -> RecoveryDecision:
        choices: tuple[tuple[bool, RecoveryStep, str, str, int], ...] = (
            (
                context.mechanical_repair_available
                and budget.mechanical_repairs < budget.max_mechanical_repairs,
                RecoveryStep.MECHANICAL_REPAIR,
                "retry",
                "apply one deterministic mechanical repair",
                budget.mechanical_repairs,
            ),
            (
                budget.reobservations < budget.max_reobservations,
                RecoveryStep.REOBSERVE,
                "reacquire_and_retry",
                "refresh browser state before another decision",
                budget.reobservations,
            ),
            (
                context.alternate_action_available
                and budget.alternate_actions < budget.max_alternate_actions,
                RecoveryStep.ALTERNATE_ACTION,
                "replan",
                "select a different bounded action",
                budget.alternate_actions,
            ),
            (
                context.system_one_available
                and budget.system_one_classifications < budget.max_system_one_classifications,
                RecoveryStep.SYSTEM_ONE_CLASSIFICATION,
                "replan",
                "classify the recovery with System One",
                budget.system_one_classifications,
            ),
            (
                context.reasoning_available and budget.normal_replans < budget.max_normal_replans,
                RecoveryStep.LUNA_NORMAL_REPLAN,
                "replan",
                "request a normal reasoning replan",
                budget.normal_replans,
            ),
            (
                context.reasoning_available
                and budget.complexity_checks < budget.max_complexity_checks,
                RecoveryStep.COMPLEXITY_GATE,
                "replan",
                "evaluate whether further reasoning needs escalation",
                budget.complexity_checks,
            ),
            (
                context.reasoning_available
                and context.very_complex
                and budget.high_replans < budget.max_high_replans,
                RecoveryStep.LUNA_HIGH_REPLAN,
                "replan",
                "request one temporary high-reasoning replan",
                budget.high_replans,
            ),
            (
                context.user_intervention_allowed and budget.user_prompts < budget.max_user_prompts,
                RecoveryStep.ASK_USER,
                "ask_user",
                "request user guidance after bounded recovery options",
                budget.user_prompts,
            ),
        )
        for allowed, step, decision, reason, attempt in choices:
            if allowed:
                self._increment(step, budget)
                return RecoveryDecision(
                    decision=decision,
                    attempt=attempt + 1,
                    max_attempts=self._limit(step, budget),
                    reason=f"{context.failure_kind.value}: {reason}",
                    step=step,
                )
        return RecoveryDecision(
            decision="terminate",
            attempt=budget.normal_replans + budget.high_replans,
            max_attempts=self.max_replans,
            reason=f"{context.failure_kind.value}: recovery budget exhausted",
            step=RecoveryStep.TERMINATE,
        )

    def decide(self, kind: FailureKind, attempt: int) -> RecoveryDecision:
        """Compatibility helper for callers that only have a replan counter."""
        if attempt < self.max_replans:
            return RecoveryDecision(
                decision="replan",
                attempt=attempt + 1,
                max_attempts=self.max_replans,
                reason=f"{kind.value}: trying alternate strategy",
                step=RecoveryStep.LUNA_NORMAL_REPLAN,
            )
        return RecoveryDecision(
            decision="escalate",
            attempt=attempt,
            max_attempts=self.max_replans,
            reason=f"{kind.value}: exhausted replans",
            step=RecoveryStep.TERMINATE,
        )

    @staticmethod
    def _increment(step: RecoveryStep, budget: RecoveryBudget) -> None:
        field_name = {
            RecoveryStep.MECHANICAL_REPAIR: "mechanical_repairs",
            RecoveryStep.REOBSERVE: "reobservations",
            RecoveryStep.ALTERNATE_ACTION: "alternate_actions",
            RecoveryStep.SYSTEM_ONE_CLASSIFICATION: "system_one_classifications",
            RecoveryStep.LUNA_NORMAL_REPLAN: "normal_replans",
            RecoveryStep.COMPLEXITY_GATE: "complexity_checks",
            RecoveryStep.LUNA_HIGH_REPLAN: "high_replans",
            RecoveryStep.ASK_USER: "user_prompts",
        }[step]
        setattr(budget, field_name, getattr(budget, field_name) + 1)

    @staticmethod
    def _limit(step: RecoveryStep, budget: RecoveryBudget) -> int:
        field_name = {
            RecoveryStep.MECHANICAL_REPAIR: "max_mechanical_repairs",
            RecoveryStep.REOBSERVE: "max_reobservations",
            RecoveryStep.ALTERNATE_ACTION: "max_alternate_actions",
            RecoveryStep.SYSTEM_ONE_CLASSIFICATION: "max_system_one_classifications",
            RecoveryStep.LUNA_NORMAL_REPLAN: "max_normal_replans",
            RecoveryStep.COMPLEXITY_GATE: "max_complexity_checks",
            RecoveryStep.LUNA_HIGH_REPLAN: "max_high_replans",
            RecoveryStep.ASK_USER: "max_user_prompts",
            RecoveryStep.TERMINATE: "max_normal_replans",
        }[step]
        return getattr(budget, field_name)
