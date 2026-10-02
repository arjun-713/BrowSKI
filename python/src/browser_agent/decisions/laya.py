"""Local CPU Laya implementation of the shared decision contract."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

from browser_agent.decisions._normalize import get_value, normalize_answer
from browser_agent.decisions.base import (
    DecisionProvider,
    DecisionQuestion,
    DecisionResult,
)
from browser_agent.decisions.calibration import CalibrationPolicy


class LayaProvider(DecisionProvider):
    name = "laya"

    def __init__(
        self,
        model: Any | None = None,
        *,
        model_id: str = "convaiinnovations/laya",
        subfolder: str = "typed-decisions",
        calibration: CalibrationPolicy | None = None,
        calibration_id: str | None = None,
    ) -> None:
        self.model_id = model_id
        self.subfolder = subfolder
        self.calibration = calibration or CalibrationPolicy()
        self.calibration_id = calibration_id
        self._model = model

    def _load_model(self) -> Any:
        if self._model is None:
            try:
                import laya  # type: ignore[import-not-found]
            except ImportError as exc:  # pragma: no cover - depends on optional extra
                raise RuntimeError(
                    'LayaProvider requires the "decisions-local" extra: '
                    'pip install "browser-agent[decisions-local]"'
                ) from exc
            self._model = laya.load(self.model_id, subfolder=self.subfolder, device="cpu")
        return self._model

    async def evaluate(
        self, state: str | Mapping[str, Any], questions: Mapping[str, DecisionQuestion]
    ) -> DecisionResult:
        if not questions:
            raise ValueError("at least one decision question is required")
        payload = {
            name: {
                "type": question.kind.value,
                "instructions": question.instructions,
                **({"criteria": question.criteria} if question.criteria is not None else {}),
            }
            for name, question in questions.items()
        }

        def predict() -> Any:
            return self._load_model().predict(state, payload)

        response = await asyncio.to_thread(predict)
        answers = get_value(response, "answers", {})
        normalized = {
            name: normalize_answer(question.kind, answers[name], question, self.calibration)
            for name, question in questions.items()
        }
        return DecisionResult(
            provider=self.name,
            model=str(get_value(response, "model", self.model_id)),
            answers=normalized,
            calibration_id=self.calibration_id,
        )
