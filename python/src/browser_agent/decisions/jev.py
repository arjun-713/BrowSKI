"""Optional TypeSafe Jev cloud implementation of the shared decision contract."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from browser_agent.decisions._normalize import get_value, normalize_answer
from browser_agent.decisions.base import (
    DecisionKind,
    DecisionProvider,
    DecisionQuestion,
    DecisionResult,
)
from browser_agent.decisions.calibration import CalibrationPolicy


class JevProvider(DecisionProvider):
    name = "jev"

    def __init__(
        self,
        client: Any | None = None,
        *,
        calibration: CalibrationPolicy | None = None,
        calibration_id: str | None = None,
    ) -> None:
        self.calibration = calibration or CalibrationPolicy()
        self.calibration_id = calibration_id
        self._client = client

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                from typesafe_sdk import AsyncTypeSafeClient  # type: ignore[import-not-found]
            except ImportError as exc:  # pragma: no cover - depends on optional extra
                raise RuntimeError(
                    'JevProvider requires the "decisions-cloud" extra: '
                    'pip install "browser-agent[decisions-cloud]"'
                ) from exc
            self._client = AsyncTypeSafeClient()
        return self._client

    async def evaluate(
        self, state: str | Mapping[str, Any], questions: Mapping[str, DecisionQuestion]
    ) -> DecisionResult:
        if not questions:
            raise ValueError("at least one decision question is required")
        try:
            from typesafe_sdk import Choice, Noul, Score  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - depends on optional extra
            raise RuntimeError(
                'JevProvider requires the "decisions-cloud" extra: '
                'pip install "browser-agent[decisions-cloud]"'
            ) from exc

        sdk_questions: dict[str, Any] = {}
        for name, question in questions.items():
            if question.kind == DecisionKind.CHOICE:
                sdk_questions[name] = Choice(
                    instructions=question.instructions, criteria=question.criteria
                )
            elif question.kind == DecisionKind.SCORE:
                sdk_questions[name] = Score(
                    instructions=question.instructions, criteria=list(question.criteria or ())
                )
            else:
                sdk_questions[name] = Noul(instructions=question.instructions)

        response = await self._get_client().system_one(state=state, questions=sdk_questions)
        normalized: dict[str, Any] = {}
        for name, question in questions.items():
            if question.kind == DecisionKind.CHOICE:
                raw = response.choices[name]
            elif question.kind == DecisionKind.SCORE:
                raw = response.scores[name]
            else:
                raw = response.nouls[name]
            normalized[name] = normalize_answer(question.kind, raw, question, self.calibration)
        return DecisionResult(
            provider=self.name,
            model=str(get_value(response, "model", "jev-latest")),
            answers=normalized,
            calibration_id=self.calibration_id,
        )
