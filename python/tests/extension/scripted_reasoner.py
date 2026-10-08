"""Deterministic provider fixture; browser, bridge, and graph stay real."""

from __future__ import annotations

import asyncio

from browser_agent.reasoning import (
    ReasoningAction,
    ReasoningContext,
    ReasoningDecision,
    ReasoningEffort,
    ReasoningOutcome,
    ReasoningPurpose,
)


class ScriptedReasoner:
    def __init__(self, *, target_name: str, evidence: str, blocked: bool = False) -> None:
        self.target_name = target_name
        self.evidence = evidence
        self.deciding = asyncio.Event()
        self.release = asyncio.Event()
        self.cancelled = asyncio.Event()
        self.contexts: list[ReasoningContext] = []
        if not blocked:
            self.release.set()

    async def reason(
        self,
        context: ReasoningContext,
        *,
        model: str,
        effort: ReasoningEffort,
    ) -> ReasoningDecision:
        del model, effort
        self.contexts.append(context)
        if context.purpose == ReasoningPurpose.PLAN:
            return ReasoningDecision(
                outcome=ReasoningOutcome.MILESTONE_PLAN,
                milestones=["Advance the demo"],
                milestone_evidence={"Advance the demo": self.evidence},
                current_subgoal="Advance the demo",
            )
        self.deciding.set()
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            self.cancelled.set()
            raise
        target = next(
            element for element in context.observation.elements if element.name == self.target_name
        )
        return ReasoningDecision(
            outcome=ReasoningOutcome.NEXT_ACTION,
            action=ReasoningAction(type="click", target_ref=target.ref),
            summary="Use the explicitly selected local demo control.",
        )
