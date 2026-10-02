"""Laya-first routing with provider-local acceptance and Jev fallback."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from browser_agent.decisions.base import DecisionProvider, DecisionQuestion, DecisionResult


class AdaptiveDecisionProvider(DecisionProvider):
    """Try Laya first; use Jev only when Laya errors or its own policy abstains."""

    name = "adaptive"

    def __init__(self, laya: DecisionProvider, jev: DecisionProvider) -> None:
        self.laya = laya
        self.jev = jev

    async def evaluate(
        self, state: str | Mapping[str, Any], questions: Mapping[str, DecisionQuestion]
    ) -> DecisionResult:
        try:
            result = await self.laya.evaluate(state, questions)
        except Exception:
            return await self.jev.evaluate(state, questions)
        if all(answer.accepted is True for answer in result.answers.values()):
            return result
        return await self.jev.evaluate(state, questions)
