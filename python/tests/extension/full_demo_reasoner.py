"""A scripted provider for software acceptance, never model-performance evidence."""

from __future__ import annotations

import asyncio
import re

from browser_agent.reasoning import (
    ReasoningAction,
    ReasoningContext,
    ReasoningDecision,
    ReasoningEffort,
    ReasoningOutcome,
    ReasoningPurpose,
)


class FullDemoReasoner:
    """Choose known fixture actions while relying on runtime memory for extraction."""

    def __init__(self) -> None:
        self.deciding = asyncio.Event()
        self.release = asyncio.Event()
        self.contexts: list[ReasoningContext] = []

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
                milestones=["Prepare the application for review"],
                milestone_evidence={
                    "Prepare the application for review": "Application ready for review"
                },
                current_subgoal="Prepare the application for review",
            )

        step = context.task.steps_taken
        if step == 0:
            # The E2E pauses before the first action to verify no scheduling.
            self.deciding.set()
            await self.release.wait()
        if step in {0, 1, 3}:
            label, value = {
                0: ("Full name", "Alex Demo"),
                1: ("Email address", "alex@example.invalid"),
                3: ("Preferred city", "Bengaluru"),
            }[step]
            action = ReasoningAction(type="type", target_ref=_ref(context, label), text=value)
        elif step == 2:
            action = ReasoningAction(
                type="click", target_ref=_ref(context, "Continue to role details")
            )
        elif step == 4:
            url_match = re.search(r'open "([^"]+)" in a new tab', context.task.task, re.I)
            assert url_match is not None
            action = ReasoningAction(type="new_tab", url=url_match.group(1))
        elif step in {5, 6}:
            if step == 5:
                description = next(
                    description
                    for description in context.candidate_options.values()
                    if description.startswith("Activate the already owned tab labeled ")
                )
            else:
                description = "Activate another already owned browser tab."
            candidate_id = next(
                candidate_id
                for candidate_id, option in context.candidate_options.items()
                if option == description
            )
            return ReasoningDecision(
                outcome=ReasoningOutcome.NEXT_ACTION,
                candidate_id=candidate_id,
                evidence_ref=_ref(context, "Reference code") if step == 6 else None,
                summary="Perform the next deterministic local-fixture step.",
            )
        elif step == 7:
            # No reference value is cached in this provider. The graph must
            # have grounded and preserved it in its typed working memory.
            evidence = context.memory.authorized_transfer_evidence
            assert len(evidence) == 1
            action = ReasoningAction(
                type="type",
                target_ref=_ref(context, "Supporting reference code"),
                text=evidence[0].value,
            )
        else:
            raise AssertionError(f"Unexpected demo step {step}; inspect runtime trace.")

        return ReasoningDecision(
            outcome=ReasoningOutcome.NEXT_ACTION,
            action=action,
            summary="Perform the next deterministic local-fixture step.",
        )


def _ref(context: ReasoningContext, label: str) -> str:
    return next(element.ref for element in context.observation.elements if element.name == label)
