"""M5 provider contract tests use fake local/cloud clients and no model downloads."""

from __future__ import annotations

import asyncio
import sys
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from browser_agent.decisions import (
    AdaptiveDecisionProvider,
    CalibrationPolicy,
    DecisionConfig,
    DecisionKind,
    DecisionProvider,
    DecisionProviderName,
    DecisionProviderProtocolError,
    DecisionProviderTimeout,
    DecisionQuestion,
    DecisionResult,
    DecisionTelemetryEvent,
    JevProvider,
    LayaProvider,
    create_decision_provider,
)


class FakeLayaModel:
    def __init__(self, answers: dict[str, Any]) -> None:
        self.answers = answers
        self.calls: list[tuple[Any, Any]] = []

    def predict(self, state: Any, questions: Any) -> dict[str, Any]:
        self.calls.append((state, questions))
        return {"model": "fake-laya", "answers": self.answers}


class FakeJevClient:
    def __init__(self, response: Any) -> None:
        self.response = response
        self.calls: list[tuple[Any, Any]] = []

    async def system_one(self, *, state: Any, questions: Any) -> Any:
        self.calls.append((state, questions))
        return self.response


class FixedProvider(DecisionProvider):
    def __init__(
        self, name: str, accepted: bool | None, value: str, error: Exception | None = None
    ) -> None:
        self.name = name
        self.accepted = accepted
        self.value = value
        self.error = error
        self.calls = 0

    async def evaluate(self, state: Any, questions: Any) -> DecisionResult:
        _ = state, questions
        self.calls += 1
        if self.error is not None:
            raise self.error
        from browser_agent.decisions import DecisionAnswer

        return DecisionResult(
            provider=self.name,
            model=None,
            answers={
                key: DecisionAnswer(
                    kind=question.kind,
                    value=self.value,
                    accepted=self.accepted,
                    confidence_raw=0.99,
                    confidence_calibrated=0.5,
                )
                for key, question in questions.items()
            },
        )


def install_fake_typesafe(monkeypatch: pytest.MonkeyPatch) -> None:
    module = ModuleType("typesafe_sdk")
    module.Choice = lambda **kwargs: SimpleNamespace(kind="choice", **kwargs)  # type: ignore[attr-defined]
    module.Score = lambda **kwargs: SimpleNamespace(kind="score", **kwargs)  # type: ignore[attr-defined]
    module.Noul = lambda **kwargs: SimpleNamespace(kind="noul", **kwargs)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "typesafe_sdk", module)


async def test_laya_maps_all_typed_questions_and_uses_its_calibration() -> None:
    model = FakeLayaModel(
        {
            "choice": {
                "choice": "safe",
                "answer_confidence": 0.8,
                "probabilities": {"safe": 0.8, "stop": 0.2},
            },
            "score": {
                "score": 2,
                "confidence": 0.7,
                "probabilities": {"0": 0.1, "1": 0.2, "2": 0.7},
            },
            "noul": {"noul": 0.9, "confidence": 0.9},
        }
    )
    provider = LayaProvider(
        model,
        calibration=CalibrationPolicy(
            temperatures={DecisionKind.CHOICE: 2.0},
            minimum_confidence={DecisionKind.CHOICE: 0.6},
        ),
        calibration_id="laya-holdout-1",
    )
    questions = {
        "choice": DecisionQuestion(DecisionKind.CHOICE, "Pick", {"safe": None, "stop": None}),
        "score": DecisionQuestion(DecisionKind.SCORE, "Rate", ("low", "mid", "high")),
        "noul": DecisionQuestion(DecisionKind.NOUL, "Is it complete?"),
    }

    result = await provider.evaluate({"page": "saved"}, questions)

    assert result.provider == "laya"
    assert result.model == "fake-laya"
    assert result.calibration_id == "laya-holdout-1"
    assert set(result.answers) == {"choice", "score", "noul"}
    assert result.answers["choice"].value == "safe"
    assert result.answers["choice"].accepted is True
    calibrated_confidence = result.answers["choice"].confidence_calibrated
    raw_confidence = result.answers["choice"].confidence_raw
    assert calibrated_confidence is not None
    assert raw_confidence is not None
    assert calibrated_confidence < raw_confidence
    assert result.answers["score"].value == 2.0
    assert result.answers["noul"].value == 0.9
    assert model.calls[0][1]["choice"]["type"] == "choice"
    assert model.calls[0][1]["choice"]["criteria"] == {"safe": "safe", "stop": "stop"}
    assert model.calls[0][1]["score"]["criteria"] == ("low", "mid", "high")


async def test_jev_maps_choice_score_noul_with_official_question_shapes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_typesafe(monkeypatch)
    client = FakeJevClient(
        SimpleNamespace(
            model="jev-latest",
            choices={
                "choice": SimpleNamespace(
                    choice="safe", confidence=0.75, probabilities={"safe": 0.75, "stop": 0.25}
                )
            },
            scores={
                "score": SimpleNamespace(
                    score=1.5, confidence=0.6, probabilities={"0": 0.2, "1": 0.4, "2": 0.4}
                )
            },
            nouls={"noul": SimpleNamespace(noul=0.8, confidence=0.8)},
        )
    )
    provider = JevProvider(
        client=client, calibration=CalibrationPolicy(minimum_confidence={DecisionKind.NOUL: 0.7})
    )
    questions = {
        "choice": DecisionQuestion(DecisionKind.CHOICE, "Pick", {"safe": None, "stop": None}),
        "score": DecisionQuestion(DecisionKind.SCORE, "Rate", ("low", "mid", "high")),
        "noul": DecisionQuestion(DecisionKind.NOUL, "Is it complete?"),
    }

    result = await provider.evaluate("page state", questions)

    assert result.provider == "jev"
    assert result.answers["choice"].value == "safe"
    assert result.answers["score"].value == 1.5
    assert result.answers["noul"].value == 0.8
    assert result.answers["noul"].accepted is True
    assert isinstance(result.answers["choice"].raw, dict)
    sent_questions = client.calls[0][1]
    assert sent_questions["choice"].criteria == {"safe": None, "stop": None}
    assert sent_questions["score"].criteria == ["low", "mid", "high"]
    assert sent_questions["noul"].kind == "noul"


async def test_decision_provider_exposes_semantic_recovery_and_progress_capabilities() -> None:
    model = FakeLayaModel(
        {
            "decision": {"choice": "reacquire", "answer_confidence": 0.7},
        }
    )
    provider = LayaProvider(model)
    assert provider.capabilities.semantic_verification
    assert provider.capabilities.recovery_classification
    assert provider.capabilities.progress_checks

    result = await provider.classify_recovery("stale reference", "target moved")
    assert result.value == "reacquire"
    assert "recovery" in model.calls[0][1]["decision"]["instructions"]

    model.answers = {"decision": {"noul": 0.95, "confidence": 0.95}}
    verified = await provider.semantic_verify("confirmation toast is visible", "saved successfully")
    progress = await provider.check_progress(
        "account page loaded", "update the profile", "settings page"
    )
    assert verified.value == 0.95
    assert progress.value == 0.95
    assert "confirm" in model.calls[1][1]["decision"]["instructions"]
    assert "progress" in model.calls[2][1]["decision"]["instructions"]


async def test_adaptive_uses_provider_specific_acceptance_without_comparing_raw_scores() -> None:
    laya = FixedProvider("laya", False, "local")
    jev = FixedProvider("jev", True, "cloud")
    adaptive = AdaptiveDecisionProvider(laya, jev)
    question = {"route": DecisionQuestion(DecisionKind.CHOICE, "Choose", {"a": None, "b": None})}

    result = await adaptive.evaluate("state", question)

    assert result.provider == "jev"
    assert result.answers["route"].value == "cloud"
    assert (laya.calls, jev.calls) == (1, 1)


async def test_adaptive_returns_laya_when_its_own_policy_accepts() -> None:
    laya = FixedProvider("laya", True, "local")
    jev = FixedProvider("jev", True, "cloud")
    result = await AdaptiveDecisionProvider(laya, jev).evaluate(
        "state", {"route": DecisionQuestion(DecisionKind.CHOICE, "Choose", {"a": None, "b": None})}
    )
    assert result.provider == "laya"
    assert (laya.calls, jev.calls) == (1, 0)


async def test_adaptive_falls_back_when_laya_raises() -> None:
    laya = FixedProvider("laya", None, "", error=RuntimeError("local model unavailable"))
    jev = FixedProvider("jev", True, "cloud")
    result = await AdaptiveDecisionProvider(laya, jev).evaluate(
        "state", {"route": DecisionQuestion(DecisionKind.CHOICE, "Choose", {"a": None, "b": None})}
    )
    assert result.provider == "jev"
    assert result.fallback_from == "laya"
    assert result.fallback_reason == "laya_error:RuntimeError"
    assert (laya.calls, jev.calls) == (1, 1)


async def test_adaptive_emits_fallback_event() -> None:
    events: list[DecisionTelemetryEvent] = []
    laya = FixedProvider("laya", False, "local")
    jev = FixedProvider("jev", True, "cloud")
    adaptive = AdaptiveDecisionProvider(laya, jev, telemetry=events.append)

    result = await adaptive.evaluate(
        "state", {"route": DecisionQuestion(DecisionKind.CHOICE, "Choose", {"a": None, "b": None})}
    )

    assert result.fallback_from == "laya"
    assert events[0].outcome == "succeeded"
    assert events[0].fallback_from == "laya"
    assert events[0].fallback_to == "jev"


async def test_provider_telemetry_includes_safe_correlation_and_reported_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_typesafe(monkeypatch)
    response = SimpleNamespace(
        model="jev-latest",
        choices={"route": SimpleNamespace(choice="safe", confidence=0.9)},
        scores={},
        nouls={},
        usage=SimpleNamespace(input_tokens=123, output_tokens=7),
    )
    events: list[DecisionTelemetryEvent] = []
    provider = JevProvider(client=FakeJevClient(response), telemetry=events.append)
    question = {
        "route": DecisionQuestion(DecisionKind.CHOICE, "Pick", {"safe": None, "stop": None})
    }

    await provider.evaluate(
        {"run_id": "run-123\nignored", "steps_taken": 4, "page": "private page text"}, question
    )

    event = events[0]
    assert event.provider == "jev"
    assert event.operation == "evaluate"
    assert event.outcome == "success"
    assert event.model == "jev-latest"
    assert event.run_id == "run-123ignored"
    assert event.step == 4
    assert event.input_tokens == 123
    assert event.output_tokens == 7


async def test_laya_telemetry_reads_only_provider_reported_token_counts() -> None:
    class UsageModel:
        def predict(self, state: Any, questions: Any) -> dict[str, Any]:
            _ = state, questions
            return {
                "answers": {"decision": {"noul": 0.95}},
                "usage": {"input_tokens": 31, "output_tokens": 4},
            }

    events: list[DecisionTelemetryEvent] = []
    provider = LayaProvider(UsageModel(), telemetry=events.append)
    await provider.probability("bounded state", "Is the expected result visible?")

    assert events[0].provider == "laya"
    assert events[0].model == "laya-local"
    assert events[0].input_tokens == 31
    assert events[0].output_tokens == 4


async def test_laya_uses_local_http_contract_and_reports_health() -> None:
    calls: list[tuple[str, str, Any, float, Any]] = []

    def transport(method: str, url: str, payload: Any, timeout: float, headers: Any) -> Any:
        calls.append((method, url, payload, timeout, headers))
        if method == "GET":
            return {"status": "ok"}
        return {"model": "laya-cpu", "answers": {"done": {"noul": 0.9, "confidence": 0.9}}}

    provider = LayaProvider(endpoint_url="http://127.0.0.1:9010/", transport=transport)
    health = await provider.health_check()
    result = await provider.evaluate(
        "visible page state", {"done": DecisionQuestion(DecisionKind.NOUL, "Is the form saved?")}
    )

    assert health.available is True
    assert calls[0][0:2] == ("GET", "http://127.0.0.1:9010/health")
    assert calls[1][0:2] == ("POST", "http://127.0.0.1:9010/v1/systemone")
    assert calls[1][2]["state"] == "visible page state"
    assert calls[1][2]["questions"]["done"]["type"] == "noul"
    assert calls[1][3] == 5.0
    assert result.model == "laya-cpu"
    assert result.answers["done"].value == 0.9


async def test_laya_absent_local_service_is_explicit_and_health_is_nonfatal() -> None:
    def unavailable(*args: Any) -> Any:
        _ = args
        raise OSError("connection refused")

    provider = LayaProvider(transport=unavailable)
    health = await provider.health_check()
    assert health.available is False
    assert health.detail == "OSError"
    with pytest.raises(DecisionProviderProtocolError, match="Laya decision failed with OSError"):
        await provider.evaluate("state", {"done": DecisionQuestion(DecisionKind.NOUL, "Done?")})


async def test_laya_timeout_is_mapped_to_typed_error() -> None:
    def timed_out(*args: Any) -> Any:
        _ = args
        raise TimeoutError("transport timeout")

    provider = LayaProvider(transport=timed_out)
    with pytest.raises(DecisionProviderTimeout):
        await provider.evaluate("state", {"done": DecisionQuestion(DecisionKind.NOUL, "Done?")})


async def test_jev_timeout_is_mapped_to_typed_error(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_typesafe(monkeypatch)

    class SlowClient:
        async def system_one(self, *, state: Any, questions: Any) -> Any:
            _ = state, questions
            await asyncio.sleep(0.05)

    provider = JevProvider(client=SlowClient(), timeout_ms=1)
    with pytest.raises(DecisionProviderTimeout):
        await provider.evaluate(
            "state", {"done": DecisionQuestion(DecisionKind.NOUL, "Is it done?")}
        )


def test_default_config_selects_local_laya_and_supports_all_switches() -> None:
    assert DecisionConfig().provider == DecisionProviderName.LAYA
    providers = {
        name: create_decision_provider(
            DecisionConfig(provider=name), laya_model=FakeLayaModel({}), jev_client=object()
        )
        for name in DecisionProviderName
    }
    assert isinstance(providers[DecisionProviderName.LAYA], LayaProvider)
    assert isinstance(providers[DecisionProviderName.JEV], JevProvider)
    assert isinstance(providers[DecisionProviderName.ADAPTIVE], AdaptiveDecisionProvider)


def test_typed_choice_is_bounded_and_calibration_settings_are_provider_specific() -> None:
    with pytest.raises(ValueError, match="2 to 16"):
        DecisionQuestion(DecisionKind.CHOICE, "Pick", {"only": None})
    config = DecisionConfig.model_validate(
        {
            "provider": "adaptive",
            "calibration": {
                "laya": {"minimum_confidence": {"choice": 0.8}},
                "jev": {"minimum_confidence": {"choice": 0.6}},
            },
        }
    )
    assert config.calibration.laya.threshold_for(DecisionKind.CHOICE) == 0.8
    assert config.calibration.jev.threshold_for(DecisionKind.CHOICE) == 0.6
