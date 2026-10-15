"""Scoped Laya decisions never expand runtime authorization or completion."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest
from test_microtask_call_budget import snapshot, task

from browser_agent._types import WorkingMemory
from browser_agent.agent.luna import LunaDecisionAgent
from browser_agent.agent.luna_candidates import action_candidates, agent_observation
from browser_agent.decisions.base import (
    DecisionAnswer,
    DecisionKind,
    DecisionProvider,
    DecisionQuestion,
    DecisionResult,
)
from browser_agent.decisions.candidates import CandidatePolicy
from browser_agent.decisions.fast_path import LayaRoutingPolicy, next_explicit_candidate


class FakeLaya(DecisionProvider):
    name = "laya"

    def __init__(self, value: str, confidence: float = 0.9) -> None:
        self.value = value
        self.confidence = confidence
        self.requests: list[str | Mapping[str, Any]] = []

    async def evaluate(
        self, state: str | Mapping[str, Any], questions: Mapping[str, DecisionQuestion]
    ) -> DecisionResult:
        self.requests.append(state)
        return DecisionResult(
            provider="laya",
            model="test",
            answers={
                key: DecisionAnswer(
                    DecisionKind.CHOICE,
                    self.value,
                    probabilities={
                        "EXECUTE_AUTHORIZED_COMMAND": 0.95,
                        "ESCALATE_TO_REASONER": 0.05,
                    },
                    raw={"answer_confidence": self.confidence},
                )
                for key in questions
            },
        )


def routing_policy(**updates: object) -> LayaRoutingPolicy:
    values: dict[str, object] = {
        "policy_id": "test-only-not-runtime-calibration",
        "checkpoint": "test-checkpoint",
        "benchmark_sha256": "0" * 64,
        "enabled": True,
        "answer_confidence_threshold": 0.8,
        "minimum_margin": 0.5,
    }
    values.update(updates)
    return LayaRoutingPolicy.model_validate(values)


async def test_eligible_command_can_use_laya_without_luna_but_value_stays_local() -> None:
    goal = 'Fill "Name" with "Ada".'
    laya = FakeLaya("EXECUTE_AUTHORIZED_COMMAND")
    agent = LunaDecisionAgent(laya, None, laya_routing_policy=routing_policy())
    decision = await agent.decide(snapshot(), task(goal), WorkingMemory(user_goal=goal))
    assert decision.action is not None
    assert decision.action.text == "Ada"
    assert decision.milestones
    assert "Ada" not in str(laya.requests)
    assert agent.last_reasoning_calls == 0
    await agent.finish_run()


@pytest.mark.parametrize(
    ("value", "confidence", "updates"),
    [
        ("ESCALATE_TO_REASONER", 0.99, {}),
        ("arbitrary_action", 0.99, {}),
        ("EXECUTE_AUTHORIZED_COMMAND", 0.2, {}),
        ("EXECUTE_AUTHORIZED_COMMAND", 0.99, {"enabled": False}),
        ("EXECUTE_AUTHORIZED_COMMAND", 0.99, {"minimum_margin": None}),
    ],
)
async def test_abstention_uncalibrated_and_unknown_values_do_not_execute(
    value: str, confidence: float, updates: dict[str, object]
) -> None:
    goal = 'Fill "Name" with "Ada".'
    laya = FakeLaya(value, confidence)
    agent = LunaDecisionAgent(laya, None, laya_routing_policy=routing_policy(**updates))
    decision = await agent.decide(snapshot(), task(goal), WorkingMemory(user_goal=goal))
    assert decision.action is None
    assert decision.ask_user
    await agent.finish_run()


def test_no_fast_path_for_generating_form_contents_or_unknown_future_controls() -> None:
    for goal in (
        "Create a questionnaire about team morale.",
        'Fill "Name" with "Ada" and click "Unobserved next page".',
        'Fill "Name" with "Ada" and then fill "Name" with "Grace".',
    ):
        state = task(goal)
        page = snapshot()
        observation = agent_observation(page)
        candidates = action_candidates(
            snapshot=page,
            task=state,
            memory=WorkingMemory(user_goal=goal),
            observation=observation,
            candidate_policy=CandidatePolicy(),
        )
        assert (
            next_explicit_candidate(state, page, observation, candidates, CandidatePolicy()) is None
        )
